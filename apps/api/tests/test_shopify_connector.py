"""Tests for the Shopify CSV connector + end-to-end upload."""

from __future__ import annotations

from io import StringIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.ingestion.connectors.shopify import (
    EXCLUDED_FINANCIAL_STATUSES,
    SHOPIFY_REQUIRED_COLS,
    detect_shopify,
    transform_shopify_to_panel,
)
from apps.api.main import app


def _shopify_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal Shopify-export DataFrame from row dicts."""
    base = pd.DataFrame(rows)
    # Make sure all required columns exist
    for col in SHOPIFY_REQUIRED_COLS:
        if col not in base.columns:
            base[col] = None
    return base


def test_detect_shopify_positive():
    df = _shopify_df([
        {"Lineitem sku": "SKU-1", "Lineitem quantity": 1, "Created at": "2026-01-01", "Financial Status": "paid"},
    ])
    assert detect_shopify(df) is True


def test_detect_shopify_missing_column():
    df = pd.DataFrame({"Lineitem sku": ["X"], "Lineitem quantity": [1]})  # missing Created at + Financial Status
    assert detect_shopify(df) is False


def test_detect_shopify_empty_df():
    assert detect_shopify(pd.DataFrame()) is False


def test_transform_shopify_aggregates_by_sku_and_date():
    df = _shopify_df([
        {"Lineitem sku": "A", "Lineitem quantity": 2, "Created at": "2026-01-01 10:00 -0700", "Financial Status": "paid", "Lineitem price": 10.0, "Lineitem name": "Widget"},
        {"Lineitem sku": "A", "Lineitem quantity": 3, "Created at": "2026-01-01 14:00 -0700", "Financial Status": "paid", "Lineitem price": 10.0, "Lineitem name": "Widget"},
        {"Lineitem sku": "B", "Lineitem quantity": 1, "Created at": "2026-01-01 10:00 -0700", "Financial Status": "paid", "Lineitem price": 25.0, "Lineitem name": "Gadget"},
    ])
    panel = transform_shopify_to_panel(df)
    assert set(panel.columns) >= {"sku_id", "date", "demand", "unit_price", "supplier", "category"}
    sku_a = panel[panel["sku_id"] == "A"]
    assert len(sku_a) == 1  # rolled up across the two timestamps in the same day
    assert sku_a["demand"].iloc[0] == 5  # 2 + 3
    sku_b = panel[panel["sku_id"] == "B"]
    assert sku_b["demand"].iloc[0] == 1
    assert (panel["supplier"] == "shopify").all()


def test_transform_shopify_excludes_cancelled_orders():
    df = _shopify_df([
        {"Lineitem sku": "A", "Lineitem quantity": 5, "Created at": "2026-01-01", "Financial Status": "paid", "Lineitem price": 10.0, "Lineitem name": "W"},
        {"Lineitem sku": "A", "Lineitem quantity": 99, "Created at": "2026-01-01", "Financial Status": "cancelled", "Lineitem price": 10.0, "Lineitem name": "W"},
        {"Lineitem sku": "A", "Lineitem quantity": 99, "Created at": "2026-01-01", "Financial Status": "refunded", "Lineitem price": 10.0, "Lineitem name": "W"},
    ])
    panel = transform_shopify_to_panel(df)
    assert (panel["demand"] == 5).all()


def test_transform_shopify_drops_empty_skus():
    df = _shopify_df([
        {"Lineitem sku": "", "Lineitem quantity": 3, "Created at": "2026-01-01", "Financial Status": "paid", "Lineitem price": 0, "Lineitem name": "Shipping fee"},
        {"Lineitem sku": "A", "Lineitem quantity": 1, "Created at": "2026-01-01", "Financial Status": "paid", "Lineitem price": 10.0, "Lineitem name": "W"},
    ])
    panel = transform_shopify_to_panel(df)
    assert len(panel) == 1
    assert panel["sku_id"].iloc[0] == "A"


def test_transform_shopify_drops_negative_quantities():
    df = _shopify_df([
        {"Lineitem sku": "A", "Lineitem quantity": -2, "Created at": "2026-01-01", "Financial Status": "paid", "Lineitem price": 10.0, "Lineitem name": "W"},
        {"Lineitem sku": "A", "Lineitem quantity": 4, "Created at": "2026-01-01", "Financial Status": "paid", "Lineitem price": 10.0, "Lineitem name": "W"},
    ])
    panel = transform_shopify_to_panel(df)
    assert panel["demand"].iloc[0] == 4


def test_transform_shopify_weighted_mean_price():
    df = _shopify_df([
        {"Lineitem sku": "A", "Lineitem quantity": 1, "Created at": "2026-01-01", "Financial Status": "paid", "Lineitem price": 10.0, "Lineitem name": "W"},
        {"Lineitem sku": "A", "Lineitem quantity": 3, "Created at": "2026-01-01", "Financial Status": "paid", "Lineitem price": 20.0, "Lineitem name": "W"},
    ])
    panel = transform_shopify_to_panel(df)
    expected = (1 * 10.0 + 3 * 20.0) / 4
    assert abs(panel["unit_price"].iloc[0] - expected) < 0.001


def test_transform_shopify_rejects_non_shopify():
    df = pd.DataFrame({"sku_id": ["A"], "demand": [1]})
    with pytest.raises(ValueError):
        transform_shopify_to_panel(df)


def test_upload_route_detects_shopify_e2e():
    rows = []
    for day in range(1, 8):
        rows.append({
            "Lineitem sku": f"SKU-{day:03d}",
            "Lineitem quantity": day + 2,
            "Created at": f"2026-01-{day:02d} 12:00 -0700",
            "Financial Status": "paid",
            "Lineitem price": 12.50,
            "Lineitem name": f"Item {day}",
        })
    df = _shopify_df(rows)
    buf = StringIO()
    df.to_csv(buf, index=False)
    content = buf.getvalue().encode("utf-8")

    client = TestClient(app)
    resp = client.post("/datasets/upload", files={"file": ("orders.csv", content, "text/csv")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["detected_connector"] == "shopify"
    # The transformed panel has the canonical columns, so mapping should be near-100%
    suggested = {m["canonical"]: m["file_column"] for m in body["suggested_mapping"]}
    assert suggested.get("sku_id") == "sku_id"
    assert suggested.get("demand") == "demand"
    assert suggested.get("date") == "date"


def test_upload_route_non_shopify_csv_still_works():
    """Regression: a CSV without Shopify columns should NOT trigger the connector path."""
    df = pd.DataFrame({
        "Item ID": ["A", "B"],
        "Day": ["2026-01-01", "2026-01-01"],
        "Units Sold": [3, 1],
    })
    buf = StringIO()
    df.to_csv(buf, index=False)
    content = buf.getvalue().encode("utf-8")

    client = TestClient(app)
    resp = client.post("/datasets/upload", files={"file": ("custom.csv", content, "text/csv")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["detected_connector"] is None
