from __future__ import annotations

import math

import numpy as np
import pytest

from apps.api.forecasting.metrics import (
    bias,
    crps_from_quantiles,
    crps_from_samples,
    mape,
    mase,
    pinball_loss,
    smape,
)


def test_mape_zero_when_perfect():
    y = np.array([10.0, 20.0, 30.0])
    assert mape(y, y) == 0.0


def test_mape_skips_zero_actuals():
    y = np.array([0.0, 10.0])
    yhat = np.array([5.0, 11.0])
    expected = abs(10.0 - 11.0) / 10.0 * 100.0
    assert mape(y, yhat) == pytest.approx(expected)


def test_smape_bounded_above_by_200():
    for _ in range(10):
        y = np.random.rand(20) * 100
        yhat = np.random.rand(20) * 100
        v = smape(y, yhat)
        assert 0.0 <= v <= 200.0


def test_mase_uses_seasonal_naive_baseline():
    rng = np.random.default_rng(0)
    train = 10 + rng.normal(0, 2, size=50)
    y = train[:5]
    yhat = train[:5] + 1.0
    naive_scale = float(np.mean(np.abs(np.diff(train))))
    expected = float(np.mean(np.abs(y - yhat))) / naive_scale
    assert mase(y, yhat, train, season_m=1) == pytest.approx(expected, rel=1e-6)


def test_mase_returns_nan_when_scale_is_zero():
    train = np.array([10.0, 10.0, 10.0])
    y = np.array([10.0])
    yhat = np.array([11.0])
    assert math.isnan(mase(y, yhat, train, season_m=1))


def test_bias_negative_when_under_forecast():
    y = np.array([10.0, 10.0, 10.0])
    yhat = np.array([5.0, 5.0, 5.0])
    assert bias(y, yhat) < 0


def test_pinball_loss_is_nonnegative_and_zero_when_perfect():
    y = np.array([10.0, 20.0])
    perfect = y.copy()
    assert pinball_loss(y, perfect, 0.5) == 0.0
    assert pinball_loss(y, np.array([5.0, 25.0]), 0.5) > 0.0


def test_pinball_loss_q95_penalizes_under_forecast_more():
    y = np.array([10.0])
    over = np.array([15.0])
    under = np.array([5.0])
    over_loss = pinball_loss(y, over, 0.95)
    under_loss = pinball_loss(y, under, 0.95)
    assert under_loss > over_loss


def test_crps_from_samples_zero_when_all_samples_match():
    y = np.array([10.0, 20.0])
    samples = np.array([[10.0, 10.0, 10.0], [20.0, 20.0, 20.0]])
    assert crps_from_samples(y, samples) == pytest.approx(0.0, abs=1e-9)


def test_crps_from_quantiles_returns_finite_for_realistic_input():
    y = np.array([10.0, 20.0])
    q_levels = np.array([0.1, 0.5, 0.9])
    q_values = np.array([
        [8.0, 10.0, 12.0],
        [18.0, 20.0, 22.0],
    ])
    v = crps_from_quantiles(y, q_levels, q_values)
    assert math.isfinite(v) and v >= 0
