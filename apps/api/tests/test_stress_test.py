"""Regression tests for the portfolio stress test.

The result carried NaN/Inf whenever a SKU was unassessable, which FastAPI then
coerces to JSON null — so var_95 / the revenue-at-risk totals rendered blank in
the UI (and the payload is invalid for any strict JSON consumer). Two sources,
both reachable from real data / the API:

  * a SKU whose recent demand window is entirely missing -> mean_d is NaN, and
  * service_level at 0/1 -> norm.ppf() is ±Inf in the safety-stock term.

These assert the result is finite (json.dumps(allow_nan=False) is exactly the
strict-JSON contract and rejects NaN/Inf).
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import duckdb
import numpy as np
import pandas as pd
import pytest

from apps.api.inventory import stress_test as st
from apps.api.inventory.stress_test import _per_sku_exposure, run_stress_test


def _mk_sku(sku_id: str, demand: list[float], on_hand: float = 5.0) -> pd.DataFrame:
    n = len(demand)
    return pd.DataFrame({
        "sku_id": [sku_id] * n,
        "date": pd.date_range("2025-01-01", periods=n, freq="W"),
        "demand": demand,
        "on_hand": [on_hand] * n,
        "unit_cost": [3.0] * n,
        "unit_price": [5.0] * n,
        "supplier": ["S1"] * n,
        "lead_time_days": [14.0] * n,
    })


# Real history followed by an all-NaN recent window: tail() is all-NaN, so the
# recent-window mean is NaN (pandas skips NaN, so a partial window would not).
_NAN_SKU = _mk_sku("SKU-NAN", [5, 6, 7, 8] + [np.nan] * 13)
_OK_SKU = _mk_sku("SKU-OK", [10, 12, 9, 11, 13, 8, 10, 12])

_EMPTY_SUPPLIERS = pd.DataFrame(columns=["name", "default_lead_time_days", "lead_time_std_days"])


def _assert_json_finite(obj: object) -> None:
    """allow_nan=False mirrors Starlette's JSONResponse.render exactly."""
    json.dumps(obj, allow_nan=False)


def test_exposure_drops_sku_with_all_nan_recent_window():
    out = _per_sku_exposure(_NAN_SKU, pd.DataFrame(), 7.0, 2.0, 1.0, 0.95)
    assert "SKU-NAN" not in out  # dropped rather than emitting NaN


def test_exposure_keeps_normal_sku_finite():
    out = _per_sku_exposure(_OK_SKU, pd.DataFrame(), 7.0, 2.0, 1.0, 0.95)
    assert "SKU-OK" in out
    assert all(np.isfinite(v) for v in out["SKU-OK"].values())


@pytest.fixture
def patch_dataset(monkeypatch):
    """Point run_stress_test at an in-memory panel/suppliers pair."""
    def _install(panel: pd.DataFrame, suppliers: pd.DataFrame) -> None:
        @contextmanager
        def fake_open(dataset_id: str, read_only: bool = False):
            conn = duckdb.connect(":memory:")
            conn.register("_panel", panel)
            conn.register("_suppliers", suppliers)
            conn.execute("CREATE TABLE panel AS SELECT * FROM _panel")
            conn.execute("CREATE TABLE suppliers AS SELECT * FROM _suppliers")
            try:
                yield conn
            finally:
                conn.close()
        monkeypatch.setattr(st, "open_dataset", fake_open)
    return _install


def test_run_stress_test_serializable_with_nan_sku(patch_dataset):
    panel = pd.concat([_OK_SKU, _NAN_SKU], ignore_index=True)
    patch_dataset(panel, _EMPTY_SUPPLIERS)

    result = run_stress_test("ds", lead_time_multiplier=2.0, demand_multiplier=1.0, service_level=0.95)

    _assert_json_finite(result)  # pre-fix: var_95 is NaN and this raises
    assert "SKU-NAN" not in {r["sku_id"] for r in result["top_impacted"]}
    assert np.isfinite(result["var_95"]) and np.isfinite(result["cvar_95"])


@pytest.mark.parametrize("service_level", [0.0, 1.0])
def test_run_stress_test_extreme_service_level_finite(patch_dataset, service_level):
    patch_dataset(_OK_SKU, _EMPTY_SUPPLIERS)

    result = run_stress_test(
        "ds", lead_time_multiplier=1.5, demand_multiplier=1.2, service_level=service_level
    )

    _assert_json_finite(result)  # pre-fix: norm.ppf(0|1) = ±Inf -> recommended_qty Inf
