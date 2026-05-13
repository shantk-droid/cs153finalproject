"""Targeted tests to close embarrassing coverage holes in the lowest-coverage modules.

Identified by `pytest --cov`: llm/insights.py (21%), forecasting/decompose.py (22%),
inventory/working_capital.py (0%). These modules already work in prod but had no unit
coverage. Two tests each — happy path + a notable edge case — to give us a regression net.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.main import app


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "datasets"
    data_dir.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def dataset_id(client: TestClient, sample_csv_bytes: bytes) -> str:
    up = client.post("/datasets/upload", files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    preview = up.json()
    mapping = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"] if s["file_column"]}
    client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)
    return preview["dataset_id"]


# ---------- llm/insights.py ----------

def test_panel_insights_returns_empty_without_api_key(monkeypatch: pytest.MonkeyPatch):
    from apps.api.llm.insights import panel_insights

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    out = panel_insights({"n_skus": 5, "total_revenue": 1000.0}, heuristics=[{"tone": "info", "text": "existing"}])
    assert out == []


def test_insights_cache_key_is_stable():
    """The cache key must be deterministic across identical inputs — otherwise repeat
    dashboard visits incur fresh LLM calls."""
    from apps.api.llm.insights import _cache_key

    ctx_a = {"n_skus": 5, "total": 100.0, "issues": ["one", "two"]}
    ctx_b = {"n_skus": 5, "total": 100.0, "issues": ["one", "two"]}
    ctx_c = {"n_skus": 5, "total": 100.0, "issues": ["one", "three"]}  # different
    assert _cache_key(ctx_a) == _cache_key(ctx_b)
    assert _cache_key(ctx_a) != _cache_key(ctx_c)


# ---------- forecasting/decompose.py ----------

def test_decompose_sku_returns_components(dataset_id: str):
    from apps.api.forecasting.decompose import decompose_sku
    from apps.api.db import open_dataset

    with open_dataset(dataset_id, read_only=True) as conn:
        sku = conn.execute("SELECT sku_id FROM panel LIMIT 1").fetchone()[0]

    out = decompose_sku(dataset_id, sku)
    assert "observed" in out and "trend" in out and "seasonal" in out and "residual" in out
    assert len(out["observed"]) == len(out["trend"]) == len(out["seasonal"]) == len(out["residual"])
    # Trend + seasonal + residual should approximately reconstruct observed
    obs = np.array(out["observed"])
    trd = np.array(out["trend"])
    sea = np.array(out["seasonal"])
    res = np.array(out["residual"])
    recon = trd + sea + res
    assert np.allclose(obs, recon, atol=1e-6)


def test_decompose_sku_raises_on_missing_sku(dataset_id: str):
    from apps.api.forecasting.decompose import decompose_sku
    with pytest.raises(ValueError):
        decompose_sku(dataset_id, "SKU-DOES-NOT-EXIST")


# ---------- inventory/working_capital.py ----------

def test_working_capital_returns_zeros_for_empty_panel():
    """Create an empty dataset and confirm working_capital handles it gracefully."""
    from apps.api.db import ensure_all_tables, ensure_panel_table, open_dataset
    from apps.api.inventory.working_capital import compute_working_capital

    dsid = "empty-test-ds"
    with open_dataset(dsid) as conn:
        ensure_panel_table(conn)
        ensure_all_tables(conn)

    out = compute_working_capital(dsid)
    assert out["inventory_value"] == 0.0
    assert out["annual_cogs"] == 0.0
    assert out["dio_days"] is None
    assert out["dpo_days"] is None


def test_working_capital_computes_for_real_dataset(dataset_id: str):
    """Sample panel has unit_cost + on_hand columns, so DIO should be computable."""
    from apps.api.inventory.working_capital import compute_working_capital

    out = compute_working_capital(dataset_id)
    assert "inventory_value" in out
    assert "annual_cogs" in out
    assert "dio_days" in out
    # With a sample panel having stock + cost, inventory_value should be > 0
    assert out["inventory_value"] > 0
