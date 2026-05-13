"""Demand-during-lead-time (LTD) distribution.

Given a forecast (point + quantiles) and a lead-time distribution, sample joint LTD paths
and report (mean, std, quantiles). Used by the (Q,R), base-stock, and newsvendor policies
to integrate over the full predictive distribution rather than the normal approximation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class LTDDistribution:
    """Empirical distribution of demand integrated over the lead time."""
    samples: np.ndarray   # shape (n_samples,)
    mean: float
    std: float

    def quantile(self, q: float) -> float:
        return float(np.quantile(self.samples, q))


def fit_lead_time_gamma(observations: pd.Series, fallback_mean: float = 14.0,
                        fallback_cv: float = 0.2) -> tuple[float, float]:
    """Fit a gamma to lead-time observations. Returns (shape, scale).

    Falls back to (1/cv^2, mean*cv^2) if fewer than 3 observations.
    """
    s = pd.to_numeric(observations, errors="coerce").dropna()
    s = s[s > 0]
    if len(s) < 3:
        cv2 = max(0.001, fallback_cv ** 2)
        return 1.0 / cv2, fallback_mean * cv2
    mean = float(s.mean())
    var = float(s.var())
    if var < 1e-9:
        return 1e3, mean / 1e3
    shape = mean ** 2 / var
    scale = var / mean
    return float(shape), float(scale)


def sample_demand_per_period(
    quantiles: dict[float, np.ndarray],
    n_samples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Reconstruct demand samples at each forecast period from a quantile grid.

    Strategy: for each period, build the empirical CDF from the provided quantiles and
    inverse-transform-sample. Returns shape (n_samples, horizon).
    """
    q_levels = sorted(quantiles.keys())
    horizon = len(quantiles[q_levels[0]])
    samples = np.empty((n_samples, horizon), dtype=float)
    levels = np.array(q_levels)
    for t in range(horizon):
        values = np.array([quantiles[q][t] for q in q_levels])
        u = rng.uniform(size=n_samples)
        samples[:, t] = np.maximum(0.0, np.interp(u, levels, values))
    return samples


def integrate_lead_time_demand(
    quantiles_per_period: dict[float, np.ndarray],
    period_length_days: float,
    lead_time_shape: float,
    lead_time_scale: float,
    n_samples: int = 5000,
    seed: int = 0,
) -> LTDDistribution:
    """Sample LTD = sum over the demand periods that fit within a sampled lead time.

    Models lead time L (in days) ~ Gamma(shape, scale). Demand is forecast in `period_length_days`
    chunks. For each draw of L:
        n_full = floor(L / period_length)
        partial_frac = (L - n_full*period_length) / period_length
        LTD = sum(d_1..d_{n_full}) + partial_frac * d_{n_full+1}
    """
    rng = np.random.default_rng(seed)
    demand_samples = sample_demand_per_period(quantiles_per_period, n_samples, rng)

    horizon = demand_samples.shape[1]
    if horizon == 0:
        return LTDDistribution(samples=np.zeros(n_samples), mean=0.0, std=0.0)

    lt_days = rng.gamma(shape=lead_time_shape, scale=lead_time_scale, size=n_samples)
    lt_periods = np.clip(lt_days / max(period_length_days, 1e-9), 0.0, horizon)
    n_full = np.floor(lt_periods).astype(int)
    partial_frac = lt_periods - n_full

    cum = np.cumsum(demand_samples, axis=1)
    cum_with_zero = np.concatenate([np.zeros((n_samples, 1)), cum], axis=1)
    full_part = cum_with_zero[np.arange(n_samples), n_full]

    next_demand = demand_samples[np.arange(n_samples), np.minimum(n_full, horizon - 1)]
    partial = partial_frac * next_demand
    overflow_mask = n_full >= horizon
    partial[overflow_mask] = 0.0

    ltd = full_part + partial
    return LTDDistribution(
        samples=ltd,
        mean=float(np.mean(ltd)),
        std=float(np.std(ltd)),
    )


def gamma_lead_time_summary(shape: float, scale: float) -> dict:
    """Return mean, std, p5, p95 of a Gamma(shape, scale) distribution."""
    mean = shape * scale
    std = float(np.sqrt(shape) * scale)
    p5 = float(stats.gamma.ppf(0.05, shape, scale=scale))
    p95 = float(stats.gamma.ppf(0.95, shape, scale=scale))
    return {"mean": float(mean), "std": std, "p5": p5, "p95": p95}
