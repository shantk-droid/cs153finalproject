"""LLM-extracted structured SKU features.

For each SKU, ask Haiku to label it on five product-aware dimensions:
    - is_perishable: bool — has a meaningful shelf life (food, flowers, etc.)
    - is_seasonal: bool — demand follows a calendar season (sunscreen, ski gear)
    - discretionary_vs_essential: float in [0,1] (0=essential like medicine, 1=fully discretionary)
    - gift_likelihood: float in [0,1] (0=never a gift, 1=primary use case is gifting)
    - weather_sensitive: bool — demand correlates with weather conditions

The five dimensions feed into apps/api/forecasting/ml.py as extra numeric features so the
global LightGBM model can pick up product-level priors the panel alone doesn't reveal.
Example: "iced coffee" gets weather_sensitive=True without us hard-coding it.

Caching: per-(category, description) sha256 hash at
{data_path}/llm_insights/sku_features.{hash}.json — same on-disk pattern as insights.py.
Cost is small (Haiku, ≤200 tokens output per call), but cache turns repeat dashboard visits
into $0. The cache key is `category + name` (NOT sku_id) so two SKUs with the same
description share the cache hit — typical for variant SKUs (color/size).

Falls back to all-False/0.5 (i.e., neutral) labels when ANTHROPIC_API_KEY is missing or the
LLM call errors. Callers should not rely on these features being present — `is_available()`
is a separate check and ml.py gates the join on it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic

from apps.api.config import get_settings
from apps.api.llm.cost_ledger import add_spend
from apps.api.llm.router import HAIKU_INPUT_PRICE_PER_M, HAIKU_OUTPUT_PRICE_PER_M

log = logging.getLogger(__name__)

SKU_FEATURES_MODEL = "claude-haiku-4-5-20251001"
SKU_FEATURES_MAX_TOKENS = 256

FEATURE_KEYS = (
    "is_perishable",
    "is_seasonal",
    "discretionary_vs_essential",
    "gift_likelihood",
    "weather_sensitive",
)


@dataclass(frozen=True)
class SkuFeatures:
    """The five-dim label per SKU. All floats are in [0, 1]; bools are 0.0 or 1.0 when fed
    into LightGBM so the column dtypes are uniform."""
    is_perishable: float
    is_seasonal: float
    discretionary_vs_essential: float
    gift_likelihood: float
    weather_sensitive: float
    source: str = "llm"  # "llm" | "heuristic" | "cache"

    def to_numeric_dict(self) -> dict[str, float]:
        """Numeric-only view for joining into ml.py's design matrix."""
        return {k: float(getattr(self, k)) for k in FEATURE_KEYS}


_NEUTRAL_FEATURES = SkuFeatures(
    is_perishable=0.0,
    is_seasonal=0.0,
    discretionary_vs_essential=0.5,
    gift_likelihood=0.0,
    weather_sensitive=0.0,
    source="heuristic",
)


_EXTRACT_TOOL = {
    "name": "label_sku",
    "description": "Emit the five-dimensional product label. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_perishable": {
                "type": "boolean",
                "description": "True if the product spoils, expires, or has a meaningful shelf life.",
            },
            "is_seasonal": {
                "type": "boolean",
                "description": "True if demand has a recurring calendar pattern (holiday, weather season, school year).",
            },
            "discretionary_vs_essential": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "0.0 = essential (medicine, basic food). 1.0 = fully discretionary (luxury, gift).",
            },
            "gift_likelihood": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Fraction of typical purchase volume bought as a gift (0.0 = never, 1.0 = primary use case).",
            },
            "weather_sensitive": {
                "type": "boolean",
                "description": "True if short-term weather meaningfully affects demand (umbrellas, ice cream, fans).",
            },
        },
        "required": list(FEATURE_KEYS),
        "additionalProperties": False,
    },
}

SKU_FEATURES_SYSTEM = """You label retail SKUs along five product-aware dimensions for an
inventory-forecasting model.

You'll receive: SKU id, category name, optional product description.

Use general knowledge — what kind of product is this, what drives demand for it. Be decisive:
your labels are an input to a forecaster, not a customer-facing message.

Examples to anchor your scale:
- "ice cream": is_perishable=true, is_seasonal=true, discretionary=0.7, gift=0.05, weather=true
- "ibuprofen": is_perishable=false (long shelf life), is_seasonal=false, discretionary=0.0, gift=0.0, weather=false
- "kayak": is_perishable=false, is_seasonal=true, discretionary=0.95, gift=0.1, weather=true
- "engagement ring": is_perishable=false, is_seasonal=false, discretionary=1.0, gift=0.9, weather=false
- "milk": is_perishable=true, is_seasonal=false, discretionary=0.0, gift=0.0, weather=false

Call the `label_sku` tool exactly once with your decision."""


def _cache_key(category: str | None, name: str | None) -> str:
    """sha256 over a canonical (category, name) so two SKUs with identical descriptions share the cache."""
    payload = json.dumps({
        "category": (category or "").strip().lower(),
        "name": (name or "").strip().lower(),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def _cache_path(key: str) -> Path:
    settings = get_settings()
    return Path(settings.data_path) / "llm_insights" / f"sku_features.{key}.json"


def _read_cache(key: str) -> SkuFeatures | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
        return SkuFeatures(**{**data, "source": "cache"})
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def _write_cache(key: str, features: SkuFeatures) -> None:
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(features)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def extract_features(
    sku_id: str,
    category: str | None,
    description: str | None = None,
    *,
    use_cache: bool = True,
) -> SkuFeatures:
    """Return the five-dim label for one SKU. Always returns a valid SkuFeatures —
    falls back to a neutral profile (0.5 across the board, all-False bools) on any error.

    The cache key is over (category, description) — not sku_id. Two SKUs with the same
    description share the cache, which is the common case for variant SKUs.
    """
    settings = get_settings()
    name = description or sku_id  # description preferred; sku_id is a poor signal but better than nothing
    key = _cache_key(category, name)

    if use_cache:
        hit = _read_cache(key)
        if hit is not None:
            return hit

    if not settings.anthropic_api_key:
        # Persist the neutral fallback so repeat calls don't keep hitting this branch
        _write_cache(key, _NEUTRAL_FEATURES)
        return _NEUTRAL_FEATURES

    user_payload = json.dumps({
        "sku_id": sku_id,
        "category": category,
        "description": description,
    })

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model=SKU_FEATURES_MODEL,
            max_tokens=SKU_FEATURES_MAX_TOKENS,
            system=SKU_FEATURES_SYSTEM,
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "label_sku"},
            messages=[{"role": "user", "content": user_payload}],
        )
    except Exception as e:
        log.warning("sku_features LLM call failed: %s", e)
        _write_cache(key, _NEUTRAL_FEATURES)
        return _NEUTRAL_FEATURES

    in_tokens = getattr(response.usage, "input_tokens", 0) or 0
    out_tokens = getattr(response.usage, "output_tokens", 0) or 0
    cost = (
        in_tokens * HAIKU_INPUT_PRICE_PER_M / 1e6
        + out_tokens * HAIKU_OUTPUT_PRICE_PER_M / 1e6
    )
    if cost > 0:
        add_spend(settings.data_path, cost, context="sku_features")

    tool_uses = [b for b in response.content if b.type == "tool_use" and b.name == "label_sku"]
    if not tool_uses:
        _write_cache(key, _NEUTRAL_FEATURES)
        return _NEUTRAL_FEATURES
    args = dict(tool_uses[0].input)
    try:
        features = SkuFeatures(
            is_perishable=1.0 if bool(args.get("is_perishable")) else 0.0,
            is_seasonal=1.0 if bool(args.get("is_seasonal")) else 0.0,
            discretionary_vs_essential=float(args.get("discretionary_vs_essential", 0.5)),
            gift_likelihood=float(args.get("gift_likelihood", 0.0)),
            weather_sensitive=1.0 if bool(args.get("weather_sensitive")) else 0.0,
            source="llm",
        )
    except (TypeError, ValueError):
        features = _NEUTRAL_FEATURES
    _write_cache(key, features)
    return features


def features_for_panel(
    panel,  # pd.DataFrame with sku_id + category columns
    *,
    use_cache: bool = True,
    max_skus_to_label: int = 200,
) -> dict[str, SkuFeatures]:
    """Batch-extract features for every unique SKU in a panel. Returns {sku_id: SkuFeatures}.

    Limited to `max_skus_to_label` to bound cost on large panels — beyond that, missing SKUs
    get the neutral fallback in `extract_features`. For the typical 50-200 SKU dataset we
    label every one; on a 1000-SKU panel we'd label the top 200 by recency / revenue and
    use the cache-only path for the rest.
    """
    if panel is None or panel.empty:
        return {}
    by_sku: dict[str, SkuFeatures] = {}
    unique = panel[["sku_id", "category"]].drop_duplicates().head(max_skus_to_label)
    for _, row in unique.iterrows():
        sku = str(row["sku_id"])
        cat = row["category"] if "category" in row.index else None
        cat_str = None if cat is None else str(cat)
        by_sku[sku] = extract_features(sku, cat_str, description=None, use_cache=use_cache)
    return by_sku


def is_available() -> bool:
    """The features module is always 'available' — falls back gracefully. ml.py uses this
    to decide whether to gate adding the columns at all (e.g., disable in tests)."""
    return True
