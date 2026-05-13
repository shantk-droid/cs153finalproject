"""statsforecast wrappers — return a uniform (point, quantiles) tuple regardless of model.

For models that don't natively emit prediction intervals (CrostonClassic, TSB), we derive
intervals from the in-sample residual standard deviation using a normal approximation.
This is a reasonable v1; Day 8's conformal wrapper replaces it with empirical-coverage intervals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import (
    AutoARIMA,
    AutoETS,
    CrostonClassic,
    SeasonalNaive,
    TSB,
)

from apps.api.forecasting.schemas import Frequency, ForecastMethod, Pattern

QUANTILES: list[float] = [0.025, 0.1, 0.5, 0.9, 0.975]
LEVELS: list[int] = [80, 95]

FREQ_TO_SEASON_M: dict[Frequency, int] = {"D": 7, "W": 52, "M": 12}
FREQ_TO_PANDAS: dict[Frequency, str] = {"D": "D", "W": "W-MON", "M": "MS"}


@dataclass
class ClassicalOutput:
    method: ForecastMethod
    point: np.ndarray            # shape (h,)
    quantiles: dict[float, np.ndarray]   # {0.025: arr(h,), 0.1: ..., ...}


def _select_model(pattern: Pattern, frequency: Frequency):
    season_m = FREQ_TO_SEASON_M[frequency]
    if pattern == "smooth":
        return AutoETS(season_length=season_m), "ets"
    if pattern == "seasonal":
        return AutoARIMA(season_length=season_m), "arima"
    if pattern == "intermittent":
        return CrostonClassic(), "croston"
    if pattern == "lumpy":
        return TSB(alpha_d=0.2, alpha_p=0.2), "tsb"
    return SeasonalNaive(season_length=season_m), "seasonal_naive"


def _normal_quantiles(point: np.ndarray, sigma: float, q_levels: list[float]) -> dict[float, np.ndarray]:
    from scipy.stats import norm
    out: dict[float, np.ndarray] = {}
    for q in q_levels:
        z = float(norm.ppf(q))
        out[q] = np.maximum(0.0, point + z * sigma)
    return out


def _residual_std(model_name: str, sf: StatsForecast, history: pd.DataFrame) -> float:
    """Best-effort in-sample residual std for fallback intervals.

    statsforecast's `forecast_fitted_values` gives in-sample fits when present; if not, we
    use a simple lag-1 difference as a proxy.
    """
    try:
        fitted = sf.forecast_fitted_values()
        if not fitted.empty and "fitted" in fitted.columns:
            resid = (history["y"].to_numpy() - fitted["fitted"].to_numpy())
            sigma = float(np.nanstd(resid))
            if sigma > 0:
                return sigma
    except Exception:
        pass
    sigma = float(np.std(np.diff(history["y"].to_numpy())))
    return sigma if sigma > 1e-9 else 1.0


def forecast_classical(
    history: pd.DataFrame,
    horizon: int,
    frequency: Frequency,
    pattern: Pattern,
) -> ClassicalOutput:
    """Run the classical model picked for the pattern + return point + 5-quantile output.

    Args:
        history: DataFrame with columns ['unique_id', 'ds', 'y'] (statsforecast format).
        horizon: number of forward steps.
        frequency: 'D', 'W', or 'M'.
        pattern: characterization label.
    """
    if "unique_id" not in history.columns or "ds" not in history.columns or "y" not in history.columns:
        raise ValueError("history must have columns: unique_id, ds, y")

    model, method_name = _select_model(pattern, frequency)
    sf = StatsForecast(models=[model], freq=FREQ_TO_PANDAS[frequency], n_jobs=1)

    if pattern in ("smooth", "seasonal", "trending_new"):
        forecasts = sf.forecast(df=history, h=horizon, level=LEVELS)
        col_point = type(model).__name__
        point = forecasts[col_point].to_numpy()
        q: dict[float, np.ndarray] = {}
        q[0.025] = forecasts[f"{col_point}-lo-95"].to_numpy()
        q[0.1] = forecasts[f"{col_point}-lo-80"].to_numpy()
        q[0.5] = point
        q[0.9] = forecasts[f"{col_point}-hi-80"].to_numpy()
        q[0.975] = forecasts[f"{col_point}-hi-95"].to_numpy()
        q = {k: np.maximum(0.0, v) for k, v in q.items()}
        return ClassicalOutput(method=method_name, point=np.maximum(0.0, point), quantiles=q)

    forecasts = sf.forecast(df=history, h=horizon)
    col_point = type(model).__name__
    point = np.maximum(0.0, forecasts[col_point].to_numpy())
    sigma = _residual_std(method_name, sf, history)
    quantiles = _normal_quantiles(point, sigma, QUANTILES)
    return ClassicalOutput(method=method_name, point=point, quantiles=quantiles)


def history_dataframe(sku_id: str, dates: pd.Series, demand: pd.Series) -> pd.DataFrame:
    """Adapter to statsforecast's expected (unique_id, ds, y) layout."""
    return pd.DataFrame({
        "unique_id": [sku_id] * len(dates),
        "ds": pd.to_datetime(dates).to_numpy(),
        "y": pd.to_numeric(demand).to_numpy(),
    })
