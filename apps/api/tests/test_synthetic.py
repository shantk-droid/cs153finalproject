from __future__ import annotations

import pandas as pd
import pytest

from apps.api.synthetic import (
    CANONICAL_COLUMNS,
    TEMPLATES,
    generate_synthetic,
    template_coffee_perishable,
    template_ecommerce_lumpy,
    template_retail_stable,
)


def test_canonical_schema_columns_match():
    df = generate_synthetic(n_skus=10, n_periods=20)
    assert list(df.columns) == CANONICAL_COLUMNS


def test_required_fields_have_no_nulls():
    df = generate_synthetic(n_skus=10, n_periods=20)
    for col in ("sku_id", "date", "demand"):
        assert df[col].notna().all(), f"{col} has nulls"


def test_panel_size():
    df = generate_synthetic(n_skus=15, n_periods=30)
    assert len(df) == 15 * 30


def test_demand_non_negative():
    df = generate_synthetic(n_skus=20, n_periods=40, intermittency_rate=0.4)
    assert (df["demand"] >= 0).all()


def test_seed_is_deterministic():
    a = generate_synthetic(n_skus=10, n_periods=20, seed=7)
    b = generate_synthetic(n_skus=10, n_periods=20, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_intermittency_rate_approximately_respected():
    df = generate_synthetic(n_skus=200, n_periods=200, intermittency_rate=0.5, seed=42)
    zero_pct = (df["demand"] == 0).mean()
    assert 0.40 < zero_pct < 0.60, f"zero_pct={zero_pct}"


def test_lead_time_present_per_supplier():
    df = generate_synthetic(n_skus=30, n_periods=20, n_suppliers=4)
    by_sup = df.groupby("supplier")["lead_time_days"].nunique()
    assert (by_sup == 1).all(), "lead time should be one value per supplier"


def test_unit_price_above_unit_cost():
    df = generate_synthetic(n_skus=30, n_periods=10)
    assert (df["unit_price"] > df["unit_cost"]).all()


def test_dates_are_timestamps():
    df = generate_synthetic(n_skus=5, n_periods=10)
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


@pytest.mark.parametrize("template_fn,name", [
    (template_retail_stable, "retail_stable"),
    (template_coffee_perishable, "coffee_perishable"),
    (template_ecommerce_lumpy, "ecommerce_lumpy"),
])
def test_each_template_returns_canonical_panel(template_fn, name):
    df = template_fn(seed=1)
    assert list(df.columns) == CANONICAL_COLUMNS
    assert df["sku_id"].nunique() == TEMPLATES[name].kwargs["n_skus"]
    assert df["demand"].notna().all()


def test_ecommerce_template_is_lumpier_than_retail():
    retail = template_retail_stable(seed=2)
    ec = template_ecommerce_lumpy(seed=2)
    assert (ec["demand"] == 0).mean() > (retail["demand"] == 0).mean()
