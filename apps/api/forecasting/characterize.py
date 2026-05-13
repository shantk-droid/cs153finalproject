"""Series characterizer.

Day 7: prefers the M5-trained LightGBM classifier when available + confident; falls back to
hand rules. The hand rules also provide the labels the classifier was trained on, so the
two are deliberately consistent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.forecasting.schemas import Frequency, Pattern

CLASSIFIER_CONFIDENCE_THRESHOLD = 0.6


def _seasonal_lags(frequency: Frequency) -> list[int]:
    if frequency == "D":
        return [7, 14, 28, 365]
    if frequency == "W":
        return [4, 13, 26, 52]
    if frequency == "M":
        return [3, 6, 12]
    return []


def _autocorr(series: np.ndarray, lag: int) -> float:
    s = series.astype(float)
    if len(s) <= lag + 1:
        return 0.0
    a = s[:-lag]
    b = s[lag:]
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a**2).sum() * (b**2).sum())
    if denom < 1e-9:
        return 0.0
    return float((a * b).sum() / denom)


def _has_significant_seasonality(series: np.ndarray, frequency: Frequency, threshold: float = 0.3) -> bool:
    for lag in _seasonal_lags(frequency):
        if len(series) > lag + 5 and _autocorr(series, lag) > threshold:
            return True
    return False


def characterize_series(series: pd.Series, frequency: Frequency) -> Pattern:
    """Map a univariate demand series to a pattern label.

    Rules (CLAUDE.md §forecasting):
    - n < 13                → trending_new
    - zero_pct > 0.7        → lumpy
    - zero_pct > 0.3        → intermittent
    - significant ACF peak  → seasonal
    - else                  → smooth
    """
    arr = np.asarray(series.dropna(), dtype=float)
    n = len(arr)
    if n < 13:
        return "trending_new"

    zero_pct = float((arr == 0).mean())
    if zero_pct > 0.7:
        return "lumpy"
    if zero_pct > 0.3:
        return "intermittent"
    if _has_significant_seasonality(arr, frequency):
        return "seasonal"
    return "smooth"


def _classifier_features(arr: np.ndarray, frequency: Frequency) -> dict:
    n = len(arr)
    nonzero = arr[arr > 0]
    return {
        "n_obs": float(n),
        "zero_pct": float((arr == 0).mean()) if n > 0 else 0.0,
        "cv_demand": float(arr.std() / arr.mean()) if arr.mean() > 0 else 0.0,
        "cv_nonzero_demand": float(nonzero.std() / nonzero.mean()) if len(nonzero) > 1 and nonzero.mean() > 0 else 0.0,
        "acf_lag_7": _autocorr(arr, 7),
        "acf_lag_28": _autocorr(arr, 28),
        "acf_lag_365": _autocorr(arr, 365) if n > 366 else 0.0,
        "trend_slope_pct": _trend_slope_pct(arr),
        "last_90d_vs_baseline_ratio": _regime_shift_ratio(arr, last=90, baseline=180),
    }


def _trend_slope_pct(arr: np.ndarray) -> float:
    if len(arr) < 30 or arr.mean() <= 0:
        return 0.0
    x = np.arange(len(arr))
    slope = float(np.polyfit(x, arr, 1)[0])
    return slope / arr.mean() * 100.0


def _regime_shift_ratio(arr: np.ndarray, last: int, baseline: int) -> float:
    if len(arr) < last + baseline:
        return 1.0
    last_mean = arr[-last:].mean()
    base_mean = arr[-(last + baseline):-last].mean()
    if base_mean <= 0:
        return 1.0
    return float(last_mean / base_mean)


def characterize_with_classifier(
    series: pd.Series,
    frequency: Frequency,
) -> tuple[Pattern, str]:
    """Try the M5-trained classifier; fall back to hand rules below the confidence threshold.

    Returns (pattern, source) where source is 'classifier' or 'rules'.
    """
    arr = np.asarray(series.dropna(), dtype=float)
    if len(arr) < 13:
        return "trending_new", "rules"

    from apps.api.m5.loader import pattern_classifier_meta, pattern_classifier_model

    model = pattern_classifier_model()
    meta = pattern_classifier_meta()
    if model is None or meta is None:
        return characterize_series(series, frequency), "rules"

    feats = _classifier_features(arr, frequency)
    feature_cols = meta["feature_cols"]
    X = pd.DataFrame([[feats[c] for c in feature_cols]], columns=feature_cols)
    proba = model.predict(X)[0]
    top_idx = int(np.argmax(proba))
    top_conf = float(proba[top_idx])
    label = meta["label_classes"][top_idx]
    if top_conf < CLASSIFIER_CONFIDENCE_THRESHOLD:
        return characterize_series(series, frequency), "rules_low_confidence"
    return label, "classifier"
