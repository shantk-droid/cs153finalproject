from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.forecasting.backtest import backtest_sku, rolling_origin_cutoffs
from apps.api.forecasting.characterize import characterize_series
from apps.api.forecasting.classical import (
    QUANTILES,
    forecast_classical,
    history_dataframe,
)


@pytest.fixture
def smooth_history():
    dates = pd.date_range("2024-01-01", periods=100, freq="W-MON")
    rng = np.random.default_rng(0)
    demand = pd.Series(50.0 + rng.normal(0, 2, size=len(dates)))
    return history_dataframe("X", pd.Series(dates), demand), pd.Series(demand)


@pytest.fixture
def intermittent_history():
    dates = pd.date_range("2024-01-01", periods=100, freq="W-MON")
    rng = np.random.default_rng(0)
    demand = pd.Series(rng.choice([0.0, 0.0, 0.0, 5.0, 8.0], size=len(dates)))
    return history_dataframe("X", pd.Series(dates), demand), pd.Series(demand)


@pytest.fixture
def seasonal_history():
    dates = pd.date_range("2024-01-01", periods=120, freq="W-MON")
    pattern = np.tile(
        np.array([10.0, 12.0, 14.0, 13.0, 11.0, 9.0, 8.0, 7.0, 8.0, 9.0, 10.0, 11.0]),
        len(dates) // 12 + 1,
    )[: len(dates)]
    demand = pd.Series(pattern + np.random.default_rng(0).normal(0, 0.3, size=len(dates)))
    return history_dataframe("X", pd.Series(dates), demand), pd.Series(demand)


def test_forecast_smooth_returns_5_quantiles(smooth_history):
    history, demand = smooth_history
    out = forecast_classical(history, horizon=4, frequency="W", pattern="smooth")
    assert out.method == "ets"
    assert len(out.point) == 4
    for q in QUANTILES:
        assert len(out.quantiles[q]) == 4
    assert (out.quantiles[0.025] <= out.quantiles[0.975]).all()


def test_forecast_intermittent_returns_nonnegative(intermittent_history):
    history, demand = intermittent_history
    pattern = characterize_series(demand, "W")
    out = forecast_classical(history, horizon=4, frequency="W", pattern=pattern)
    assert out.method in {"croston", "tsb"}
    assert (out.point >= 0).all()


def test_forecast_seasonal_path(seasonal_history):
    history, demand = seasonal_history
    out = forecast_classical(history, horizon=12, frequency="W", pattern="seasonal")
    assert out.method == "arima"
    assert len(out.point) == 12


def test_rolling_origin_cutoffs_returns_at_most_n_folds():
    cutoffs = rolling_origin_cutoffs(n=100, n_folds=4, horizon=4)
    assert len(cutoffs) <= 4
    assert all(c < 100 - 4 + 1 for c in cutoffs)


def test_rolling_origin_cutoffs_empty_when_too_short():
    assert rolling_origin_cutoffs(n=10, n_folds=4, horizon=4) == []


def test_backtest_smooth_returns_finite_metrics(smooth_history):
    history, demand = smooth_history
    dates = pd.to_datetime(history["ds"])
    result = backtest_sku("X", dates, demand, frequency="W", horizon=4, n_folds=3)
    assert result.n_folds >= 1
    assert result.crps is None or result.crps >= 0


def test_backtest_returns_zero_folds_for_short_series():
    dates = pd.Series(pd.date_range("2024-01-01", periods=8, freq="W-MON"))
    demand = pd.Series([10.0] * 8)
    result = backtest_sku("X", dates, demand, frequency="W", horizon=4, n_folds=3)
    assert result.n_folds == 0
