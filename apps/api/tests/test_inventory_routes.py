from __future__ import annotations

from pathlib import Path

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
def confirmed_dataset_id(client: TestClient, sample_csv_bytes: bytes) -> str:
    up = client.post("/datasets/upload", files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    preview = up.json()
    mapping = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"] if s["file_column"]}
    client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)
    return preview["dataset_id"]


def test_skus_listing_returns_rows(client: TestClient, confirmed_dataset_id: str):
    r = client.get(f"/datasets/{confirmed_dataset_id}/skus?limit=10")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) > 0
    first = rows[0]
    assert "abc_class" in first and "xyz_class" in first
    assert first["abc_class"] in {"A", "B", "C"}


def test_skus_listing_filters_by_abc(client: TestClient, confirmed_dataset_id: str):
    r = client.get(f"/datasets/{confirmed_dataset_id}/skus?limit=200&abc=A")
    assert r.status_code == 200
    rows = r.json()
    assert all(r["abc_class"] == "A" for r in rows)


def test_aggregate_stats_returns_heatmap(client: TestClient, confirmed_dataset_id: str):
    r = client.get(f"/datasets/{confirmed_dataset_id}/aggregate_stats")
    assert r.status_code == 200, r.text
    stats = r.json()
    heatmap = stats["abc_xyz_heatmap"]
    assert set(heatmap.keys()) == {"AX", "AY", "AZ", "BX", "BY", "BZ", "CX", "CY", "CZ"}
    assert sum(heatmap.values()) == stats["n_skus"]


def test_recommend_returns_full_recommendation(client: TestClient, confirmed_dataset_id: str):
    listing = client.get(f"/datasets/{confirmed_dataset_id}/skus?limit=1").json()
    sku_id = listing[0]["sku_id"]
    r = client.post(f"/datasets/{confirmed_dataset_id}/skus/{sku_id}/recommend", json={})
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["sku_id"] == sku_id
    assert rec["policy_name"] in {"EOQ", "(Q,R)", "(s,S)", "newsvendor", "base-stock"}
    assert rec["recommended_order_qty"] >= 0
    assert 0.0 <= rec["expected_stockout_prob"] <= 1.0
    assert 0.0 <= rec["expected_fill_rate"] <= 1.0
    assert rec["abc_class"] in {"A", "B", "C"}


def test_recommend_with_overrides_changes_safety_stock(client: TestClient, confirmed_dataset_id: str):
    listing = client.get(f"/datasets/{confirmed_dataset_id}/skus?limit=1").json()
    sku_id = listing[0]["sku_id"]
    rec_90 = client.post(f"/datasets/{confirmed_dataset_id}/skus/{sku_id}/recommend",
                         json={"service_level": 0.90}).json()
    rec_99 = client.post(f"/datasets/{confirmed_dataset_id}/skus/{sku_id}/recommend",
                         json={"service_level": 0.99}).json()
    assert rec_99["safety_stock"] >= rec_90["safety_stock"]


def test_aggregate_stats_404_for_unknown_dataset(client: TestClient):
    r = client.get("/datasets/no-such-id/aggregate_stats")
    assert r.status_code == 404
