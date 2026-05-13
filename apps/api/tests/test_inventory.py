from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from apps.api.inventory.abc_xyz import classify_abc_xyz, heatmap_counts
from apps.api.inventory.distributions import (
    fit_lead_time_gamma,
    integrate_lead_time_demand,
    sample_demand_per_period,
)
from apps.api.inventory.policies import (
    base_stock,
    eoq,
    newsvendor,
    qr_policy,
)


# --- EOQ ---

def test_eoq_textbook_example():
    """Annual demand 1200, order cost $10, holding $1/unit/yr → Q* = sqrt(2*1200*10/1) = 154.92"""
    res = eoq(1200, 10.0, 1.0)
    assert res.Q == pytest.approx(154.919, abs=0.01)
    assert res.expected_orders_per_year == pytest.approx(1200 / 154.919, abs=0.01)
    assert res.total_cost_annual == pytest.approx(154.919, abs=0.5)


def test_eoq_rejects_non_positive():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            eoq(bad, 10, 1)
        with pytest.raises(ValueError):
            eoq(100, bad, 1)
        with pytest.raises(ValueError):
            eoq(100, 10, bad)


# --- (Q, R) ---

def test_qr_normal_demand_R_close_to_z_score():
    rng = np.random.default_rng(0)
    samples = rng.normal(loc=100, scale=10, size=20000)
    res = qr_policy(samples, annual_demand=5000, order_cost=10, holding_cost_per_unit=1, service_level=0.95)
    assert 113 <= res.R <= 119  # mean=100, z_95 ≈ 1.645, sigma=10 → R≈116
    assert 0.94 <= 1 - res.expected_stockout_prob <= 0.96


def test_qr_safety_stock_grows_with_service_level():
    rng = np.random.default_rng(0)
    samples = rng.normal(100, 10, size=10000)
    res_90 = qr_policy(samples, 5000, 10, 1, 0.90)
    res_99 = qr_policy(samples, 5000, 10, 1, 0.99)
    assert res_99.safety_stock > res_90.safety_stock


# --- newsvendor ---

def test_newsvendor_critical_ratio_normal():
    rng = np.random.default_rng(0)
    samples = rng.normal(100, 10, size=20000)
    res = newsvendor(samples, underage_cost=4.0, overage_cost=1.0)
    # Cu/(Cu+Co) = 0.8 → q ≈ mean + 0.842 * sigma ≈ 108.4
    assert 106 <= res.Q <= 112


def test_newsvendor_underage_only():
    samples = np.array([10.0, 20.0, 30.0, 40.0])
    res = newsvendor(samples, 100.0, 1.0)
    assert res.Q == pytest.approx(np.quantile(samples, 100/101), rel=1e-2)


# --- base-stock ---

def test_base_stock_returns_quantile():
    samples = np.linspace(0, 100, 1001)
    res = base_stock(samples, 0.95)
    assert res.S == pytest.approx(95.0, abs=0.1)


# --- distributions ---

def test_fit_lead_time_gamma_falls_back_when_short():
    s = pd.Series([10.0])
    shape, scale = fit_lead_time_gamma(s, fallback_mean=14, fallback_cv=0.2)
    assert shape * scale == pytest.approx(14.0)


def test_fit_lead_time_gamma_recovers_mean_cv():
    rng = np.random.default_rng(0)
    truth_mean = 14.0
    truth_cv = 0.3
    shape = 1 / truth_cv ** 2
    scale = truth_mean / shape
    sample = pd.Series(rng.gamma(shape, scale, size=500))
    fitted_shape, fitted_scale = fit_lead_time_gamma(sample)
    fitted_mean = fitted_shape * fitted_scale
    assert truth_mean * 0.85 <= fitted_mean <= truth_mean * 1.15


def test_sample_demand_per_period_shape():
    quantiles = {0.025: np.array([5.0]), 0.1: np.array([7.0]),
                 0.5: np.array([10.0]), 0.9: np.array([13.0]), 0.975: np.array([15.0])}
    rng = np.random.default_rng(0)
    samples = sample_demand_per_period(quantiles, n_samples=1000, rng=rng)
    assert samples.shape == (1000, 1)
    assert (samples >= 0).all()


def test_integrate_lead_time_demand_mean_close_to_expected():
    quantiles = {0.025: np.array([8, 8, 8, 8, 8, 8, 8, 8, 8, 8.0]),
                 0.1: np.array([9.0] * 10),
                 0.5: np.array([10.0] * 10),
                 0.9: np.array([11.0] * 10),
                 0.975: np.array([12.0] * 10)}
    ltd = integrate_lead_time_demand(
        quantiles_per_period=quantiles,
        period_length_days=7.0,
        lead_time_shape=49.0,
        lead_time_scale=14.0/49.0,
        n_samples=5000,
        seed=0,
    )
    assert 18 <= ltd.mean <= 22


# --- ABC/XYZ ---

def test_abc_xyz_assigns_a_to_top_revenue_skus():
    dates = pd.date_range("2024-01-01", periods=52, freq="W-MON")
    rows = []
    for i in range(20):
        revenue_factor = (20 - i) ** 2
        for d in dates:
            rows.append({
                "sku_id": f"SKU-{i:03d}",
                "date": d,
                "demand": revenue_factor,
                "unit_price": 10.0,
                "unit_cost": 5.0,
            })
    df = pd.DataFrame(rows)
    out = classify_abc_xyz(df)
    top = out[0]
    assert top.abc == "A"
    assert top.sku_id == "SKU-000"


def test_heatmap_counts_sums_to_total():
    dates = pd.date_range("2024-01-01", periods=52, freq="W-MON")
    rng = np.random.default_rng(0)
    rows = []
    for i in range(50):
        for d in dates:
            rows.append({
                "sku_id": f"SKU-{i:03d}",
                "date": d,
                "demand": float(rng.poisson(10)),
                "unit_price": 5.0,
                "unit_cost": 2.0,
            })
    df = pd.DataFrame(rows)
    out = classify_abc_xyz(df)
    counts = heatmap_counts(out)
    assert sum(counts.values()) == 50
