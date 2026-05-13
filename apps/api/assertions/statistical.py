"""Distribution-profile DQ component — soft-penalty match against a reference profile.

For each SKU, compute the same five panel-level metrics
(cv_demand, intermittency_rate, regime_shift_score, trend_slope_pct, seasonality_strength)
that the profile's bands describe, then score each metric on a piecewise soft-penalty
curve anchored at the profile's p2/p10/p90/p98 percentiles.

Score 100 inside [p10, p90]; ramp to 50 at p2/p98; decay to 0 outside.
Aggregate: mean across the five metrics per SKU, then **median** across SKUs.

Anomaly counts are reported as values outside [p10, p90] — informational, not penalty-driving.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from apps.api.profiles import Profile, score_metric

METRICS = ("cv_demand", "intermittency_rate", "seasonality_strength",
           "trend_slope_pct", "regime_shift_score")


@dataclass
class DistributionAnomaly:
    sku_id: str
    metric: str
    value: float
    profile_p10: float
    profile_p90: float
    side: str  # "below_p10", "above_p90"


def _autocorr(arr: np.ndarray, lag: int) -> float:
    if len(arr) <= lag + 1:
        return 0.0
    a = arr[:-lag] - arr[:-lag].mean()
    b = arr[lag:] - arr[lag:].mean()
    denom = np.sqrt((a**2).sum() * (b**2).sum())
    return 0.0 if denom < 1e-9 else float((a * b).sum() / denom)


def _trend_slope_pct(arr: np.ndarray) -> float:
    if len(arr) < 30 or arr.mean() <= 0:
        return 0.0
    x = np.arange(len(arr))
    slope = float(np.polyfit(x, arr, 1)[0])
    return abs(slope / arr.mean() * 100.0)


def _regime_shift_score(arr: np.ndarray, last: int = 90, baseline: int = 180) -> float:
    if len(arr) < last + baseline:
        return 0.0
    last_mean = arr[-last:].mean()
    base_mean = arr[-(last + baseline):-last].mean()
    if base_mean <= 0:
        return 0.0
    return abs(float(last_mean / base_mean) - 1.0)


def metrics_for_sku(arr: np.ndarray) -> dict[str, float]:
    """Compute the 5 reference metrics on a 1-D demand array."""
    nonzero = arr[arr > 0]
    return {
        "cv_demand": float(arr.std() / arr.mean()) if arr.mean() > 0 else 0.0,
        "intermittency_rate": float((arr == 0).mean()) if len(arr) > 0 else 0.0,
        "seasonality_strength": max(_autocorr(arr, 7), _autocorr(arr, 28), _autocorr(arr, 365)),
        "trend_slope_pct": _trend_slope_pct(arr),
        "regime_shift_score": _regime_shift_score(arr),
    }


def _matched_dept_row(ref: pd.DataFrame, dept_user: str | None, metric: str) -> pd.Series | None:
    """M5 dept-matching helper, kept for /calibration backwards compat."""
    rows_metric = ref[ref["metric"] == metric]
    if rows_metric.empty:
        return None
    if dept_user:
        u = dept_user.upper()
        exact = rows_metric[rows_metric["dept_id"].str.upper() == u]
        if not exact.empty:
            return exact.iloc[0]
        prefix = rows_metric[rows_metric["dept_id"].str.upper().str.startswith(u.split("_")[0])]
        if not prefix.empty:
            return prefix.sort_values("n_skus", ascending=False).iloc[0]
    default = rows_metric[rows_metric["dept_id"] == "_default"]
    if not default.empty:
        return default.iloc[0]
    return rows_metric.iloc[0]


def panel_metric_medians(panel: pd.DataFrame) -> dict[str, float]:
    """Median per metric across SKUs — the 5-D vector used to auto-detect a profile."""
    rows: list[dict[str, float]] = []
    for _sku_id, g in panel.groupby("sku_id"):
        arr = g["demand"].to_numpy(dtype=float)
        if len(arr) < 8:
            continue
        rows.append(metrics_for_sku(arr))
    if not rows:
        return {m: 0.0 for m in METRICS}
    df = pd.DataFrame(rows)
    return {m: float(df[m].median()) for m in METRICS}


def evaluate_panel(
    panel: pd.DataFrame,
    profile: Profile,
) -> tuple[float | None, list[DistributionAnomaly], list[str], dict[str, int]]:
    """Score the user's panel against the supplied profile.

    Returns (component_score in [0, 100] or None if too few SKUs evaluable,
    anomalies outside [p10, p90], notes, per-metric flagged counts).
    """
    anomalies: list[DistributionAnomaly] = []
    sku_scores: list[float] = []
    flagged_by_metric: dict[str, int] = {m: 0 for m in METRICS}

    for sku_id, g in panel.groupby("sku_id"):
        arr = g["demand"].to_numpy(dtype=float)
        if len(arr) < 8:
            continue
        m = metrics_for_sku(arr)
        per_metric_scores: list[float] = []
        for metric_name in METRICS:
            band = profile.bands.get(metric_name)
            if band is None:
                continue
            value = m[metric_name]
            per_metric_scores.append(score_metric(value, band))
            if value < band.p10 or value > band.p90:
                flagged_by_metric[metric_name] += 1
                anomalies.append(DistributionAnomaly(
                    sku_id=str(sku_id),
                    metric=metric_name,
                    value=float(value),
                    profile_p10=float(band.p10),
                    profile_p90=float(band.p90),
                    side="below_p10" if value < band.p10 else "above_p90",
                ))
        if per_metric_scores:
            sku_scores.append(float(np.mean(per_metric_scores)))

    notes: list[str] = []
    if not sku_scores:
        return None, [], ["no SKUs had ≥8 observations to evaluate"], flagged_by_metric

    score = round(float(np.median(sku_scores)), 2)
    n_total = len(sku_scores)
    notes.append(f"profile={profile.id}; median soft-penalty score across {n_total} SKUs")
    flagged_summary = {k: v for k, v in flagged_by_metric.items() if v}
    if flagged_summary:
        notes.append("flagged outside [p10, p90]: " + ", ".join(
            f"{k}={v}" for k, v in sorted(flagged_summary.items(), key=lambda kv: -kv[1])
        ))
    return score, anomalies, notes, flagged_by_metric
