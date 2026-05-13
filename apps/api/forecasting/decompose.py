"""STL-style decomposition + calendar effect overlay for one SKU.

Returns observed / trend / seasonal / residual components for charting.
Uses a rolling-mean / period-mean decomposition (no statsmodels dep) so it
works on short series and intermittent demand.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from apps.api.db import open_dataset
from apps.api.ingestion.validators import infer_frequency

FREQ_TO_SEASONAL_PERIOD = {"D": 7, "W": 52, "M": 12}


def _rolling_trend(series: np.ndarray, window: int) -> np.ndarray:
    if len(series) < window:
        window = max(2, len(series) // 2)
    s = pd.Series(series).rolling(window=window, min_periods=1, center=True).mean()
    return s.to_numpy()


def _seasonal_component(series: np.ndarray, period: int) -> np.ndarray:
    if len(series) < period * 2:
        return np.zeros_like(series)
    detrended = series - _rolling_trend(series, window=period)
    means = np.zeros(period)
    counts = np.zeros(period)
    for i, v in enumerate(detrended):
        if not np.isnan(v):
            means[i % period] += v
            counts[i % period] += 1
    means = np.divide(means, np.maximum(counts, 1))
    means -= means.mean()
    out = np.array([means[i % period] for i in range(len(series))])
    return out


def decompose_sku(dataset_id: str, sku_id: str) -> dict:
    sku_id = sku_id.strip().upper()
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT date, demand FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id],
        ).fetchdf()
    if df.empty:
        raise ValueError(f"SKU {sku_id} not found")
    if len(df) < 12:
        raise ValueError(f"SKU {sku_id} has only {len(df)} obs — need at least 12 for decomposition")

    frequency = infer_frequency(df["date"]) or "W"
    period = FREQ_TO_SEASONAL_PERIOD[frequency]
    period = min(period, max(2, len(df) // 3))

    observed = df["demand"].astype(float).to_numpy()
    trend = _rolling_trend(observed, window=max(period, 4))
    seasonal = _seasonal_component(observed, period)
    residual = observed - trend - seasonal

    return {
        "dates": [pd.Timestamp(d).date().isoformat() for d in df["date"]],
        "observed": [float(v) for v in observed],
        "trend": [float(v) for v in trend],
        "seasonal": [float(v) for v in seasonal],
        "residual": [float(v) for v in residual],
        "calendar_lift": None,
        "seasonal_period": int(period),
    }
