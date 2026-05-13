from __future__ import annotations

import math

import numpy as np
import pytest

from apps.api.forecasting.bayes import (
    GammaPrior,
    fit_prior_from_means,
    forecast_bayes_cold_start,
    posterior,
    predictive_quantiles,
    prior_weight_fraction,
)


def test_default_prior_is_returned_for_short_series():
    p = fit_prior_from_means(np.array([10.0]))
    assert p.source == "default"


def test_fit_prior_recovers_method_of_moments():
    rng = np.random.default_rng(0)
    means = rng.gamma(shape=4.0, scale=2.0, size=200)
    p = fit_prior_from_means(means)
    expected_mean = float(np.mean(means))
    fitted_mean = p.alpha / p.beta
    assert math.isclose(fitted_mean, expected_mean, rel_tol=0.02)


def test_posterior_alpha_grows_with_observations():
    prior = GammaPrior(alpha=2.0, beta=1.0)
    obs = np.array([5.0, 10.0, 8.0])
    a, b = posterior(prior, obs)
    assert a == 2.0 + 23.0
    assert b == 1.0 + 3.0


def test_predictive_quantiles_monotonic_in_q():
    qs = predictive_quantiles(alpha_post=10.0, beta_post=2.0,
                              q_levels=[0.025, 0.1, 0.5, 0.9, 0.975])
    keys = sorted(qs.keys())
    values = [qs[k] for k in keys]
    assert values == sorted(values)


def test_prior_weight_decreases_with_more_data():
    prior = GammaPrior(alpha=5.0, beta=2.0)
    w_few = prior_weight_fraction(prior, n_obs=2)
    w_many = prior_weight_fraction(prior, n_obs=200)
    assert w_few > w_many
    assert 0.0 <= w_many <= 1.0


def test_forecast_bayes_cold_start_constant_over_horizon():
    prior = GammaPrior(alpha=4.0, beta=1.0)
    out = forecast_bayes_cold_start(np.array([3.0, 5.0, 4.0]), prior, horizon=4)
    assert len(out.point) == 4
    assert np.allclose(out.point, out.point[0])
    for q, arr in out.quantiles.items():
        assert len(arr) == 4
        assert np.allclose(arr, arr[0])


def test_forecast_bayes_with_strong_prior_dominates_data():
    """Strong prior (alpha=1000, beta=10, mean=100) + 2 obs (mean=1.5) → posterior
    mean = (1000 + 3) / (10 + 2) ≈ 83.6. Still much closer to the prior than to data."""
    strong_prior = GammaPrior(alpha=1000.0, beta=10.0)
    out = forecast_bayes_cold_start(np.array([1.0, 2.0]), strong_prior, horizon=4)
    assert out.mean > 50, "posterior mean should be dominated by prior, not pulled to data"
    assert abs(out.mean - 83.583) < 0.5, "closed-form sanity"
