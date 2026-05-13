"""Tests for Day-11 multi-period schedule + Day-12 joint replen + settings + export."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.inventory.joint_replen import recommend_joint_replenishment
from apps.api.inventory.multi_period import (
    Schedule,
    generate_qr_schedule,
    generate_schedule,
    generate_ss_schedule,
)
from apps.api.inventory.settings import (
    DatasetSettings,
    load_dataset_settings,
    save_dataset_settings,
)
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
def confirmed_dataset(client: TestClient, sample_csv_bytes: bytes) -> str:
    up = client.post("/datasets/upload", files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    preview = up.json()
    mapping = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"] if s["file_column"]}
    client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)
    return preview["dataset_id"]


# --- multi-period schedule ---

def test_qr_schedule_orders_when_on_hand_drops_below_R():
    forecast = np.full(20, 10.0)
    sched = generate_qr_schedule(
        sku_id="X",
        forecast_point=forecast,
        starting_on_hand=80,
        Q=50, R=30,
        lead_time_days=14,
        frequency="W",
        start_date=pd.Timestamp("2025-01-01").date(),
    )
    assert sched.n_orders > 0
    actions = [e.action for e in sched.entries]
    assert "order" in actions
    assert "delivery" in actions


def test_qr_schedule_no_orders_when_safe():
    forecast = np.full(10, 1.0)
    sched = generate_qr_schedule(
        sku_id="X",
        forecast_point=forecast,
        starting_on_hand=1000,
        Q=50, R=30,
        lead_time_days=14,
        frequency="W",
        start_date=pd.Timestamp("2025-01-01").date(),
    )
    assert sched.n_orders == 0
    assert all(e.action == "no_op" for e in sched.entries)


def test_ss_schedule_review_period_respected():
    forecast = np.full(12, 10.0)
    sched = generate_ss_schedule(
        sku_id="X",
        forecast_point=forecast,
        starting_on_hand=20,
        s=15, S=80,
        review_period_periods=4,
        lead_time_days=7,
        frequency="W",
        start_date=pd.Timestamp("2025-01-01").date(),
    )
    order_periods = [e.period_idx for e in sched.entries if e.action == "order"]
    for p in order_periods:
        assert p % 4 == 0


def test_generate_schedule_dispatches_by_mode():
    forecast = np.full(8, 10.0)
    qr = generate_schedule(
        sku_id="X", forecast_point=forecast, starting_on_hand=40,
        policy_mode="QR", parameters={"Q": 30, "R": 20},
        lead_time_days=7, frequency="W",
        start_date=pd.Timestamp("2025-01-01").date(),
    )
    assert isinstance(qr, Schedule)
    ss = generate_schedule(
        sku_id="X", forecast_point=forecast, starting_on_hand=40,
        policy_mode="sS", parameters={"s": 20, "S": 60}, review_period_periods=2,
        lead_time_days=7, frequency="W",
        start_date=pd.Timestamp("2025-01-01").date(),
    )
    assert isinstance(ss, Schedule)


# --- joint replenishment ---

def test_joint_replen_groups_skus_with_similar_cycles():
    rng = np.random.default_rng(0)
    rows = []
    for sku_idx in range(5):
        for d in range(52):
            rows.append({
                "sku_id": f"A-{sku_idx}",
                "demand": 100 + rng.normal(0, 5),
                "supplier": "VENDOR-A",
                "unit_cost": 10.0,
            })
    for sku_idx in range(5):
        for d in range(52):
            rows.append({
                "sku_id": f"B-{sku_idx}",
                "demand": 200 + rng.normal(0, 5),
                "supplier": "VENDOR-B",
                "unit_cost": 5.0,
            })
    panel = pd.DataFrame(rows)
    groups = recommend_joint_replenishment(
        panel=panel, annualization_factor=52,
        order_cost_default=50, holding_cost_rate_default=0.25,
    )
    assert len(groups) >= 1
    suppliers = {g.supplier for g in groups}
    assert suppliers.issubset({"VENDOR-A", "VENDOR-B"})


def test_joint_replen_returns_empty_for_single_sku_supplier():
    panel = pd.DataFrame([
        {"sku_id": "X", "demand": 10.0, "supplier": "ONLY", "unit_cost": 1.0}
        for _ in range(52)
    ])
    groups = recommend_joint_replenishment(
        panel=panel, annualization_factor=52, order_cost_default=50, holding_cost_rate_default=0.25,
    )
    assert groups == []


# --- settings ---

def test_settings_round_trip():
    """isolated_data_dir fixture already provides the per-test data dir."""
    settings_obj = DatasetSettings(
        service_level=0.97, holding_cost_rate=0.30, order_cost=75, review_period_days=21,
        notes="custom",
    )
    save_dataset_settings("test-id", settings_obj)
    loaded = load_dataset_settings("test-id")
    assert loaded.service_level == 0.97
    assert loaded.notes == "custom"


def test_settings_defaults_when_no_file():
    loaded = load_dataset_settings("nonexistent")
    assert loaded.service_level == 0.95


def test_settings_route_get_put(client: TestClient, confirmed_dataset: str):
    r = client.get(f"/datasets/{confirmed_dataset}/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["service_level"] == 0.95

    new = {**body, "service_level": 0.99, "order_cost": 75}
    r2 = client.put(f"/datasets/{confirmed_dataset}/settings", json=new)
    assert r2.status_code == 200
    assert r2.json()["service_level"] == 0.99


def test_settings_validation_rejects_out_of_range(client: TestClient, confirmed_dataset: str):
    r = client.put(f"/datasets/{confirmed_dataset}/settings", json={"service_level": 1.5})
    assert r.status_code == 422


# --- export ---

def test_export_csv_route(client: TestClient, confirmed_dataset: str):
    r = client.get(f"/datasets/{confirmed_dataset}/export?fmt=csv&sample_skus=3")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "sku_id" in r.text and "policy" in r.text


def test_export_xlsx_route(client: TestClient, confirmed_dataset: str):
    r = client.get(f"/datasets/{confirmed_dataset}/export?fmt=xlsx&sample_skus=3")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    df = pd.read_excel(BytesIO(r.content))
    assert "sku_id" in df.columns
    assert len(df) <= 3


# --- joint replen route ---

def test_joint_replen_route(client: TestClient, confirmed_dataset: str):
    r = client.get(f"/datasets/{confirmed_dataset}/joint_replenishment")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# --- calibration route ---

def test_calibration_route(client: TestClient, confirmed_dataset: str):
    listing = client.get(f"/datasets/{confirmed_dataset}/skus?limit=1").json()
    sku = listing[0]["sku_id"]
    r = client.get(f"/datasets/{confirmed_dataset}/skus/{sku}/calibration")
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body and "comparisons" in body
