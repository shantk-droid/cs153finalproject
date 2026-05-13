"""Day-8 unit tests: conformal, ensemble, plus light availability checks for foundation/ml."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.forecasting.classical import QUANTILES
from apps.api.forecasting.conformal import (
    apply_conformal_to_quantiles,
    calibrate_residuals,
    residuals_from_backtest,
)
from apps.api.forecasting.ensemble import EnsembleMember, combine, crps_weights
from apps.api.forecasting import foundation, ml


# --- conformal ---

def test_calibrate_residuals_returns_quantile():
    resid = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    half = calibrate_residuals(resid, level=0.8)
    assert 4.0 <= half <= 5.0


def test_apply_conformal_widens_intervals_when_residuals_large():
    point = np.array([10.0, 10.0, 10.0])
    quantiles = {q: np.full(3, 10.0) for q in QUANTILES}
    quantiles[0.025] = np.full(3, 9.0)
    quantiles[0.975] = np.full(3, 11.0)
    resid = np.random.default_rng(0).normal(0, 5, size=200)
    new_quantiles, cal = apply_conformal_to_quantiles(point, quantiles, resid)
    assert (new_quantiles[0.975] >= quantiles[0.975]).all()
    assert (new_quantiles[0.025] <= quantiles[0.025]).all()
    assert cal[0.95].n_residuals == 200


def test_apply_conformal_does_not_make_intervals_negative():
    point = np.array([2.0])
    quantiles = {q: np.full(1, 2.0) for q in QUANTILES}
    resid = np.array([100.0, -100.0, 50.0, -50.0])
    new_quantiles, _ = apply_conformal_to_quantiles(point, quantiles, resid)
    assert (new_quantiles[0.025] >= 0).all()


def test_residuals_from_backtest_diff():
    a = np.array([10.0, 12.0])
    p = np.array([9.0, 13.0])
    out = residuals_from_backtest(a, p)
    assert np.allclose(out, np.array([1.0, -1.0]))


# --- ensemble ---

def test_crps_weights_inverse_of_crps():
    members = [
        EnsembleMember("a", np.array([1.0]), {q: np.array([1.0]) for q in QUANTILES}, crps_backtest=2.0),
        EnsembleMember("b", np.array([1.0]), {q: np.array([1.0]) for q in QUANTILES}, crps_backtest=4.0),
    ]
    w = crps_weights(members)
    assert w["a"] > w["b"]
    assert pytest.approx(sum(w.values()), abs=1e-6) == 1.0


def test_crps_weights_equal_when_all_none():
    members = [
        EnsembleMember("a", np.array([1.0]), {q: np.array([1.0]) for q in QUANTILES}, crps_backtest=None),
        EnsembleMember("b", np.array([1.0]), {q: np.array([1.0]) for q in QUANTILES}, crps_backtest=None),
    ]
    w = crps_weights(members)
    assert pytest.approx(w["a"], rel=1e-6) == 0.5
    assert pytest.approx(w["b"], rel=1e-6) == 0.5


def test_combine_returns_weighted_average():
    members = [
        EnsembleMember(
            "a", np.array([10.0]),
            {q: np.array([10.0 if q == 0.5 else 8.0 if q < 0.5 else 12.0]) for q in QUANTILES},
            crps_backtest=1.0,
        ),
        EnsembleMember(
            "b", np.array([20.0]),
            {q: np.array([20.0 if q == 0.5 else 18.0 if q < 0.5 else 22.0]) for q in QUANTILES},
            crps_backtest=1.0,
        ),
    ]
    point, quantiles, weights = combine(members)
    assert pytest.approx(point[0], abs=0.01) == 15.0
    assert pytest.approx(quantiles[0.5][0], abs=0.01) == 15.0


def test_combine_raises_on_empty():
    with pytest.raises(ValueError):
        combine([])


# --- foundation / ml availability ---

def test_foundation_is_available_iff_chronos_imports():
    """Just sanity-check the helper. Doesn't load weights."""
    available = foundation.is_available()
    if available:
        try:
            import chronos  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            pytest.fail("is_available()=True but imports fail")


def test_ml_is_available():
    assert ml.is_available()


# --- ml: feature engineering on tiny synthetic panel ---

def test_ml_design_matrix_includes_lag_and_calendar():
    from apps.api.forecasting.ml import _build_design_matrix
    rng = np.random.default_rng(0)
    rows = []
    for sku in ["A", "B"]:
        for i in range(60):
            rows.append({
                "sku_id": sku,
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=i),
                "demand": 10 + rng.normal(0, 1),
                "category": "C1",
                "supplier": "S1",
            })
    panel = pd.DataFrame(rows)
    df, feature_cols, cat_cols = _build_design_matrix(panel, "W")
    assert "lag_1" in feature_cols and "lag_4" in feature_cols
    assert "rmean_4" in feature_cols
    assert "dow" in feature_cols and "month" in feature_cols
    assert "sku_id" in cat_cols
