"""Empirical-Bayes Poisson-Gamma cold-start forecast.

Used when n_obs < threshold (low-history SKUs). Closed-form posterior:

    Prior:        lambda ~ Gamma(alpha, beta)               [from series_priors.parquet]
    Likelihood:   y_i ~ Poisson(lambda)                     [observed demand]
    Posterior:    lambda ~ Gamma(alpha + sum(y), beta + n)
    Predictive:   y* ~ NegativeBinomial(r=alpha+sum(y), p=(beta+n)/(beta+n+1))

For SKUs with rich history, the posterior is data-driven and shrinkage is near-zero — so
we only call this branch when n_obs is small, to avoid paying the cost otherwise.

Day 8 will extend with seasonal/trend components; v1 ships a flat predictive distribution
across the horizon, which is the right thing for very-short cold-start series anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom


@dataclass
class GammaPrior:
    alpha: float
    beta: float
    n_observed_skus: int = 0
    source: str = "default"

    @classmethod
    def default(cls) -> "GammaPrior":
        return cls(alpha=1.0, beta=0.1, n_observed_skus=0, source="default")


@dataclass
class BayesPosterior:
    alpha_post: float
    beta_post: float
    mean: float
    var: float
    point: np.ndarray
    quantiles: dict[float, np.ndarray]


def fit_prior_from_means(mean_demands, *, mom_floor: float = 1e-3) -> GammaPrior:
    """Method-of-moments Gamma fit over a vector of per-SKU mean demands.

    Accepts pandas Series, numpy array, or any array-like.
    """
    s = pd.Series(mean_demands)
    s = pd.to_numeric(s, errors="coerce").dropna()
    s = s[s > 0]
    if len(s) < 3:
        return GammaPrior.default()
    m = float(s.mean())
    v = float(s.var())
    if v < mom_floor:
        return GammaPrior(alpha=max(1.0, m), beta=1.0, n_observed_skus=len(s), source="degenerate_var")
    alpha = m * m / v
    beta = m / v
    return GammaPrior(alpha=float(alpha), beta=float(beta), n_observed_skus=len(s), source="m5")


def posterior(prior: GammaPrior, observations: np.ndarray) -> tuple[float, float]:
    """Closed-form Gamma posterior given Poisson observations."""
    y = np.asarray(observations, dtype=float)
    n = len(y)
    sum_y = float(np.sum(y))
    return float(prior.alpha + sum_y), float(prior.beta + n)


def predictive_quantiles(alpha_post: float, beta_post: float, q_levels: list[float]) -> dict[float, float]:
    """For NegBin posterior predictive y* ~ NB(r=alpha_post, p=beta_post/(beta_post+1)),
    return the q-quantile for each level in q_levels.
    """
    r = alpha_post
    p = beta_post / (beta_post + 1.0)
    return {q: float(nbinom.ppf(q, r, p)) for q in q_levels}


def forecast_bayes_cold_start(
    observations: np.ndarray,
    prior: GammaPrior,
    horizon: int,
    q_levels: list[float] | None = None,
) -> BayesPosterior:
    """Produce a flat-over-horizon NegBin predictive distribution.

    Returns the canonical 5-level quantile grid that fits into the Forecast object.
    """
    if q_levels is None:
        q_levels = [0.025, 0.1, 0.5, 0.9, 0.975]
    alpha_post, beta_post = posterior(prior, observations)
    mean_pred = alpha_post / beta_post
    var_pred = mean_pred * (beta_post + 1.0) / beta_post

    q_singletons = predictive_quantiles(alpha_post, beta_post, q_levels)
    point = np.full(horizon, mean_pred)
    quantiles = {q: np.full(horizon, q_singletons[q]) for q in q_levels}
    return BayesPosterior(
        alpha_post=alpha_post,
        beta_post=beta_post,
        mean=mean_pred,
        var=var_pred,
        point=point,
        quantiles=quantiles,
    )


def prior_weight_fraction(prior: GammaPrior, n_obs: int) -> float:
    """How much of the posterior is driven by the prior vs the data, in [0, 1].

    Helpful for surfacing in the Forecast.diagnostics so the user knows when shrinkage matters.
    """
    if prior.beta + n_obs <= 0:
        return 0.0
    return float(prior.beta / (prior.beta + n_obs))
