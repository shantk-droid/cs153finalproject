"""Split-conformal calibration for prediction intervals.

The base forecaster's intervals (ETS, ARIMA, Chronos quantiles, normal-approx for Croston)
have whatever coverage they have. Conformal calibration *guarantees* — under exchangeability
of residuals — that the calibrated intervals achieve the nominal coverage on average.

Approach: take the most recent backtest fold's residuals (actual − point), find the empirical
quantile q_alpha of |residual|, and widen the (or replace the) interval as
    point ± q_alpha
for the symmetric version, or asymmetric quantiles of (actual − qX_low) and (qX_high − actual)
for the per-side version.

This v1 ships the symmetric variant — it's what the inventory math really cares about. Day 11+
can upgrade to asymmetric if needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class ConformalCalibration:
    nominal_coverage: float
    empirical_coverage: float | None
    half_width: float
    n_residuals: int


def calibrate_residuals(residuals: np.ndarray, level: float) -> float:
    """Return the empirical quantile of |residual| for the given coverage level.

    Coverage 0.95 → use the 95th percentile of |residual|.
    """
    abs_resid = np.abs(np.asarray(residuals, dtype=float))
    abs_resid = abs_resid[~np.isnan(abs_resid)]
    if len(abs_resid) < 2:
        return 0.0
    return float(np.quantile(abs_resid, level))


def apply_conformal_to_quantiles(
    point: np.ndarray,
    quantiles: dict[float, np.ndarray],
    residuals: np.ndarray,
    levels: tuple[float, ...] = (0.80, 0.95),
) -> tuple[dict[float, np.ndarray], dict[float, ConformalCalibration]]:
    """Replace the existing 80/95% intervals with conformal-calibrated ones.

    For each requested coverage level (0.80 → q 0.1/0.9; 0.95 → q 0.025/0.975), we widen
    around the point forecast by the conformal half-width. The 50% (median) and the
    point forecast are left unchanged. Returns the new quantile dict and per-level calibration metadata.
    """
    out = {q: arr.copy() for q, arr in quantiles.items()}
    calibrations: dict[float, ConformalCalibration] = {}

    for level in levels:
        half = calibrate_residuals(residuals, level)
        lo_q = round((1 - level) / 2, 3)
        hi_q = round(1 - (1 - level) / 2, 3)
        if half > 0:
            out[lo_q] = np.maximum(0.0, point - half)
            out[hi_q] = np.maximum(0.0, point + half)
        empirical = float(np.mean(np.abs(residuals) <= half)) if half > 0 else None
        calibrations[level] = ConformalCalibration(
            nominal_coverage=level,
            empirical_coverage=empirical,
            half_width=half,
            n_residuals=int(len(residuals)),
        )
    return out, calibrations


def residuals_from_backtest(actuals: np.ndarray, point_forecasts: np.ndarray) -> np.ndarray:
    """Return (actual − point) for use as conformity scores."""
    return np.asarray(actuals, dtype=float) - np.asarray(point_forecasts, dtype=float)
