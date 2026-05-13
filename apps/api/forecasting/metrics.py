"""Forecast accuracy metrics.

CRPS — Continuous Ranked Probability Score — is the right loss for inventory because the
inventory math integrates over the full predictive distribution. Pinball-loss-at-q95 is a
direct proxy for "how good is the safety-stock quantile we'll feed to (Q,R)?"
"""

from __future__ import annotations

import numpy as np


def mape(y: np.ndarray, yhat: np.ndarray) -> float:
    """Mean Absolute Percentage Error. Skips entries where y == 0 to avoid blowup."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.abs(y) > 1e-9
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs((y[mask] - yhat[mask]) / y[mask])) * 100.0)


def smape(y: np.ndarray, yhat: np.ndarray) -> float:
    """Symmetric MAPE — bounded in [0, 200], handles zeros gracefully."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    denom = np.abs(y) + np.abs(yhat)
    mask = denom > 1e-9
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(2.0 * np.abs(y[mask] - yhat[mask]) / denom[mask]) * 100.0)


def mase(y: np.ndarray, yhat: np.ndarray, y_train: np.ndarray, season_m: int = 1) -> float:
    """Mean Absolute Scaled Error. Scale = mean abs seasonal-naive error on train."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    y_train = np.asarray(y_train, dtype=float)
    if len(y_train) <= season_m:
        return float("nan")
    naive_diffs = np.abs(y_train[season_m:] - y_train[:-season_m])
    scale = np.mean(naive_diffs)
    if scale < 1e-9:
        return float("nan")
    return float(np.mean(np.abs(y - yhat)) / scale)


def bias(y: np.ndarray, yhat: np.ndarray) -> float:
    """Mean error normalized by mean(|y|). Negative = under-forecast."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    denom = np.mean(np.abs(y))
    if denom < 1e-9:
        return float("nan")
    return float(np.mean(yhat - y) / denom)


def pinball_loss(y: np.ndarray, q_hat: np.ndarray, q_level: float) -> float:
    """Pinball (quantile) loss at level q. Lower = better."""
    y = np.asarray(y, dtype=float)
    q_hat = np.asarray(q_hat, dtype=float)
    diff = y - q_hat
    loss = np.where(diff >= 0, q_level * diff, (q_level - 1) * diff)
    return float(np.mean(loss))


def crps_from_samples(y: np.ndarray, samples: np.ndarray) -> float:
    """CRPS estimated from forecast samples. Uses the energy-form estimator.

    Args:
        y: shape (h,) actuals.
        samples: shape (h, n_samples) draws from the predictive distribution.
    """
    y = np.asarray(y, dtype=float)
    samples = np.asarray(samples, dtype=float)
    if samples.ndim == 1:
        samples = samples[:, None]
    n = samples.shape[1]
    term1 = np.mean(np.abs(samples - y[:, None]), axis=1)
    if n > 1:
        diffs = np.abs(samples[:, :, None] - samples[:, None, :])
        term2 = 0.5 * np.mean(diffs.reshape(samples.shape[0], -1), axis=1)
    else:
        term2 = np.zeros_like(term1)
    return float(np.mean(term1 - term2))


def crps_from_quantiles(y: np.ndarray, q_levels: np.ndarray, q_values: np.ndarray) -> float:
    """CRPS approximation as a sum of pinball losses across quantile levels.

    Args:
        y: shape (h,) actuals.
        q_levels: shape (k,) quantile levels in [0, 1], strictly increasing.
        q_values: shape (h, k) predicted quantile values for each horizon step.
    """
    q_levels = np.asarray(q_levels, dtype=float)
    q_values = np.asarray(q_values, dtype=float)
    y = np.asarray(y, dtype=float)
    losses = []
    for j, q in enumerate(q_levels):
        losses.append(pinball_loss(y, q_values[:, j], float(q)))
    return float(2.0 * np.mean(losses))
