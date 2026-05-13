"""Stationarity / regime-stability DQ component.

For each SKU, compute three signals over the most recent window:
  1. Pettitt change-point test on the last 90 days (or 13 weeks).
  2. Mann-Kendall trend test comparing last vs prior period.
  3. Rolling-mean shift z-score: |mean_last_30 − mean_prior_60| / std_prior_60.

Aggregate into a 0–100 stationarity score per SKU; the component score is the mean.
SKUs flagged with structural breaks are surfaced for chat-layer caveats.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class StationarityFlag:
    sku_id: str
    pettitt_pvalue: float | None
    mk_pvalue: float | None
    shift_zscore: float | None
    score: float
    reason: str | None


def _pettitt(series: np.ndarray) -> tuple[float | None, float | None]:
    """Pettitt's change-point test (non-parametric).

    Returns (test_stat, approximate_pvalue). Smaller p-value → more evidence of a break.
    Implementation: classical formulation; pvalue via the standard asymptotic approximation.
    """
    n = len(series)
    if n < 20:
        return None, None
    s = np.asarray(series, dtype=float)
    ranks = stats.rankdata(s)
    U = np.zeros(n - 1)
    for k in range(1, n):
        U[k - 1] = 2 * np.sum(ranks[:k]) - k * (n + 1)
    K = float(np.max(np.abs(U)))
    p = 2 * np.exp(-6 * K**2 / (n**3 + n**2)) if n**3 + n**2 > 0 else None
    return K, min(1.0, p) if p is not None else None


def _mann_kendall(series: np.ndarray) -> tuple[float | None, float | None]:
    """Mann-Kendall trend test. Returns (S, two-sided pvalue)."""
    n = len(series)
    if n < 10:
        return None, None
    s = np.asarray(series, dtype=float)
    S = 0
    for i in range(n - 1):
        S += np.sign(s[i + 1:] - s[i]).sum()
    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    if var_s <= 0:
        return float(S), None
    if S > 0:
        z = (S - 1) / np.sqrt(var_s)
    elif S < 0:
        z = (S + 1) / np.sqrt(var_s)
    else:
        z = 0.0
    pvalue = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(S), float(pvalue)


def _rolling_shift_zscore(series: np.ndarray, last: int, baseline: int) -> float | None:
    if len(series) < last + baseline:
        return None
    arr = np.asarray(series, dtype=float)
    last_arr = arr[-last:]
    prior_arr = arr[-(last + baseline):-last]
    sd = prior_arr.std()
    if sd < 1e-9:
        return 0.0
    return float(abs(last_arr.mean() - prior_arr.mean()) / sd)


def _frequency_window(frequency: str) -> tuple[int, int]:
    """(last_window, baseline_window) per frequency."""
    if frequency == "D":
        return 30, 60
    if frequency == "W":
        return 4, 13
    return 3, 6  # monthly


def evaluate_panel(panel: pd.DataFrame, frequency: str) -> tuple[float | None, list[StationarityFlag]]:
    """Score the panel's stationarity. Returns (component_score in [0, 100], per-SKU flags)."""
    last, baseline = _frequency_window(frequency)
    flags: list[StationarityFlag] = []

    for sku_id, g in panel.groupby("sku_id"):
        s = g.sort_values("date")["demand"].to_numpy(dtype=float)
        if len(s) < last + baseline:
            continue
        _, pettitt_p = _pettitt(s[-(last + baseline):])
        _, mk_p = _mann_kendall(s[-(last + baseline):])
        z = _rolling_shift_zscore(s, last=last, baseline=baseline)

        score = 100.0
        reasons: list[str] = []
        if pettitt_p is not None and pettitt_p < 0.05:
            score -= 30
            reasons.append(f"Pettitt change-point p={pettitt_p:.3f}")
        if mk_p is not None and mk_p < 0.05:
            score -= 15
            reasons.append(f"Mann-Kendall trend p={mk_p:.3f}")
        if z is not None and z > 2.0:
            score -= 25
            reasons.append(f"rolling-mean shift z={z:.2f}σ")
        score = max(0.0, score)

        flags.append(StationarityFlag(
            sku_id=str(sku_id),
            pettitt_pvalue=pettitt_p,
            mk_pvalue=mk_p,
            shift_zscore=z,
            score=score,
            reason="; ".join(reasons) if reasons else None,
        ))

    if not flags:
        return None, []
    component_score = round(float(np.mean([f.score for f in flags])), 2)
    return component_score, flags


def regime_break_skus(flags: list[StationarityFlag], score_threshold: float = 70.0) -> list[str]:
    """SKUs whose stationarity score is below threshold — surfaced as caveats in forecasts/chat."""
    return [f.sku_id for f in flags if f.score < score_threshold]
