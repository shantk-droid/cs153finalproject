"""LLMTime — LLM-as-forecaster via in-context learning (Gruver et al. NeurIPS 2023).

Tokenize the SKU's recent history as a comma-separated string of numerical demands, ask
Haiku to emit the next `horizon` values, parse back. Add as an ensemble member alongside
classical / chronos / lightgbm.

Cost-aware design:
- **Off by default.** Enable per call with `enable_llm_forecaster=True` (forecast_sku param)
  or globally with the `ENABLE_LLM_FORECASTER=1` env var. Each call costs ~$0.001 (Haiku);
  with 200 SKUs forecast on dashboard load that's $0.20/refresh, easily over budget.
- **Cache by (series-hash, horizon)** at {data_path}/llm_insights/llm_forecast.{key}.json.
  Repeat backtests don't re-call. The hash includes horizon so we don't return a 4-step
  forecast when asked for 12.
- **Quantiles**: point-only from the model, then a residual-based normal approximation
  (matches the pattern in ml.py:184). LLMs don't reliably emit calibrated quantiles, so
  we don't ask.

Failure modes — all return None so the ensemble silently drops the member:
- ANTHROPIC_API_KEY missing
- Anthropic call errors
- LLM emits fewer than `horizon` values, or non-numeric tokens
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic
import numpy as np

from apps.api.config import get_settings
from apps.api.forecasting.classical import QUANTILES
from apps.api.llm.cost_ledger import add_spend
from apps.api.llm.router import HAIKU_INPUT_PRICE_PER_M, HAIKU_OUTPUT_PRICE_PER_M

log = logging.getLogger(__name__)

LLM_FORECASTER_MODEL = "claude-haiku-4-5-20251001"
LLM_FORECASTER_MAX_TOKENS = 512
MAX_HISTORY_POINTS = 60  # cap input length — Haiku handles 200K context but long inputs blow cost
MIN_HISTORY_POINTS = 8   # below this the forecast isn't worth running


@dataclass
class LlmForecastOutput:
    method: str
    point: np.ndarray
    quantiles: dict[float, np.ndarray]


_FORECAST_TOOL = {
    "name": "emit_forecast",
    "description": "Emit your numerical point forecast. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "values": {
                "type": "array",
                "items": {"type": "number", "minimum": 0},
                "description": "The forecast — one non-negative number per future period.",
            },
        },
        "required": ["values"],
        "additionalProperties": False,
    },
}


LLM_FORECASTER_SYSTEM = """You are an expert time-series forecaster for retail demand data.

Given a sequence of recent demand values (one per period — could be days, weeks, or months),
extrapolate the next `horizon` values. Read the pattern carefully:

- Intermittent series (lots of zeros mixed with small positives): forecast the running mean,
  rounded; don't try to "predict" individual zeros.
- Trending series (monotonic up or down): extrapolate the trend but don't overshoot — recent
  moves are noisier than they look.
- Seasonal series (peaks every N periods): repeat the most recent cycle; if length unclear,
  default to the most recent period's average.
- Lumpy/spiky series: smooth toward the running mean; don't replicate spikes.

Output every value as a non-negative number (rounded to one decimal is fine). Length must
equal the requested horizon exactly. Call the `emit_forecast` tool ONCE."""


def is_available() -> bool:
    """True iff feature flag is on AND an API key is set. Single source of truth for the
    ensemble's gating decision."""
    if os.environ.get("ENABLE_LLM_FORECASTER", "0") != "1":
        return False
    return bool(get_settings().anthropic_api_key)


def _series_hash(series: np.ndarray, horizon: int) -> str:
    arr = np.asarray(series, dtype=float)
    # Round to integers for a stable hash — sub-unit differences don't change the forecast meaningfully
    canonical = json.dumps({
        "values": [round(float(v), 2) for v in arr.tolist()],
        "horizon": int(horizon),
    }, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def _cache_path(key: str) -> Path:
    settings = get_settings()
    return Path(settings.data_path) / "llm_insights" / f"llm_forecast.{key}.json"


def _read_cache(key: str) -> list[float] | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
        values = data.get("values")
        if isinstance(values, list) and all(isinstance(v, (int, float)) for v in values):
            return [float(v) for v in values]
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _write_cache(key: str, values: list[float]) -> None:
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump({"values": values}, f, indent=2)
    tmp.replace(path)


def _residual_sigma(series: np.ndarray) -> float:
    """Cheap proxy for forecast uncertainty: std of the most-recent residual-like quantity.

    Use stdev of period-to-period changes rather than raw stdev so the sigma stays sensible
    for trending series. Floor at 1.0 unit so quantiles aren't collapsed for very flat series.
    """
    arr = np.asarray(series, dtype=float)
    if len(arr) < 3:
        return 1.0
    diffs = np.diff(arr[-min(20, len(arr)):])
    sigma = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else 1.0
    return max(sigma, 1.0)


def _serialize_history(series: np.ndarray) -> str:
    """Tail-truncate to MAX_HISTORY_POINTS and format as a comma-separated string.

    The LLM sees recent context only — older points dilute the more-informative recent ones,
    and tokens cost money."""
    arr = np.asarray(series, dtype=float)
    arr = arr[-MAX_HISTORY_POINTS:]
    return ", ".join(f"{v:.2f}" if abs(v) < 1e6 else f"{v:.0f}" for v in arr)


def forecast_llm(series: np.ndarray, horizon: int) -> LlmForecastOutput | None:
    """Run LLMTime on one series. Returns None when unavailable or on any failure.

    The point forecast comes from Haiku; quantiles are a normal approximation around the
    point using residual sigma from the recent history. Cached by (series-hash, horizon).
    """
    if not is_available():
        return None
    arr = np.asarray(series, dtype=float)
    if len(arr) < MIN_HISTORY_POINTS:
        return None
    if horizon < 1 or horizon > 52:
        return None

    key = _series_hash(arr, horizon)
    cached = _read_cache(key)
    point_values: list[float] | None = cached

    if point_values is None:
        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        prompt = (
            f"Recent demand (one value per period, oldest first):\n{_serialize_history(arr)}\n\n"
            f"Forecast horizon: {horizon} periods.\n"
            f"Call `emit_forecast` with exactly {horizon} non-negative numbers."
        )
        try:
            response = client.messages.create(
                model=LLM_FORECASTER_MODEL,
                max_tokens=LLM_FORECASTER_MAX_TOKENS,
                system=LLM_FORECASTER_SYSTEM,
                tools=[_FORECAST_TOOL],
                tool_choice={"type": "tool", "name": "emit_forecast"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            log.warning("LLMTime forecaster API call failed: %s", e)
            return None

        in_tokens = getattr(response.usage, "input_tokens", 0) or 0
        out_tokens = getattr(response.usage, "output_tokens", 0) or 0
        cost = (
            in_tokens * HAIKU_INPUT_PRICE_PER_M / 1e6
            + out_tokens * HAIKU_OUTPUT_PRICE_PER_M / 1e6
        )
        if cost > 0:
            add_spend(settings.data_path, cost, context="llm_forecaster")

        tool_uses = [b for b in response.content if b.type == "tool_use" and b.name == "emit_forecast"]
        if not tool_uses:
            return None
        values = tool_uses[0].input.get("values") if isinstance(tool_uses[0].input, dict) else None
        if not isinstance(values, list):
            return None
        try:
            point_values = [max(0.0, float(v)) for v in values]
        except (TypeError, ValueError):
            return None
        # Length validation: pad with the running mean if short, truncate if long.
        if len(point_values) < horizon:
            mean = float(np.mean(arr[-min(8, len(arr)):]))
            point_values = point_values + [max(0.0, mean)] * (horizon - len(point_values))
        elif len(point_values) > horizon:
            point_values = point_values[:horizon]
        _write_cache(key, point_values)

    point = np.array(point_values, dtype=float)
    sigma = _residual_sigma(arr)

    quantiles: dict[float, np.ndarray] = {}
    for q in QUANTILES:
        # Inverse-normal table inline to avoid scipy dependency here (the rest of the
        # forecasting code already uses scipy, but we cap this module's surface area).
        z = _norm_ppf(q)
        quantiles[q] = np.maximum(0.0, point + z * sigma)

    return LlmForecastOutput(method="llm_time", point=point, quantiles=quantiles)


def _norm_ppf(q: float) -> float:
    """Hot-path approximation to the inverse normal CDF.

    Acklam's algorithm — accurate to ~5 decimal places over [1e-9, 1 - 1e-9]. Avoids
    bringing in scipy.stats just for one function call per forecast horizon. Matches the
    z-multipliers ml.py uses elsewhere (it imports scipy.stats.norm).
    """
    if q <= 0 or q >= 1:
        # Clamp; callers shouldn't pass 0 or 1 but defensive.
        q = min(max(q, 1e-6), 1 - 1e-6)
    # Coefficients
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    if q < plow:
        s = math.sqrt(-2 * math.log(q))
        return (((((c[0] * s + c[1]) * s + c[2]) * s + c[3]) * s + c[4]) * s + c[5]) / \
               ((((d[0] * s + d[1]) * s + d[2]) * s + d[3]) * s + 1)
    if q <= phigh:
        s = q - 0.5
        r = s * s
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * s / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    s = math.sqrt(-2 * math.log(1 - q))
    return -(((((c[0] * s + c[1]) * s + c[2]) * s + c[3]) * s + c[4]) * s + c[5]) / \
            ((((d[0] * s + d[1]) * s + d[2]) * s + d[3]) * s + 1)
