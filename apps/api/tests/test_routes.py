from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.main import app


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each test gets its own data directory so fixtures don't collide."""
    data_dir = tmp_path / "datasets"
    data_dir.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_upload_then_confirm_round_trip(client: TestClient, sample_csv_bytes: bytes):
    r = client.post(
        "/datasets/upload",
        files={"file": ("retail.csv", sample_csv_bytes, "text/csv")},
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["dataset_id"]
    assert preview["n_total_rows"] > 0
    assert len(preview["sample_rows"]) <= 20

    suggested = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"]}
    assert suggested["sku_id"] == "sku_id"
    assert suggested["date"] == "date"
    assert suggested["demand"] == "demand"

    mapping = {k: v for k, v in suggested.items() if v is not None}
    r = client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["n_skus"] > 0
    assert summary["n_rows"] > 0
    assert summary["frequency"] in {"D", "W", "M"}


def test_upload_rejects_unsupported_extension(client: TestClient):
    r = client.post(
        "/datasets/upload",
        files={"file": ("bad.parquet", b"\x00\x00", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_confirm_rejects_unmapped_required(client: TestClient, sample_csv_bytes: bytes):
    up = client.post("/datasets/upload",
                     files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    dataset_id = up.json()["dataset_id"]
    bad_mapping = {"sku_id": "sku_id", "date": "date", "demand": "demand_does_not_exist"}
    r = client.post(f"/datasets/{dataset_id}/confirm", json=bad_mapping)
    assert r.status_code in {400, 422, 500}


def test_dq_report_endpoint_after_confirm(client: TestClient, sample_csv_bytes: bytes):
    up = client.post("/datasets/upload",
                     files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    preview = up.json()
    suggested = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"]}
    mapping = {k: v for k, v in suggested.items() if v is not None}
    client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)

    r = client.get(f"/datasets/{preview['dataset_id']}/quality")
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["dataset_id"] == preview["dataset_id"]
    assert "components" in report
    assert {c["name"] for c in report["components"]} == {
        "completeness", "plausibility", "distribution_profile", "history_depth", "stationarity"
    }


def test_dq_report_404_for_unknown_dataset(client: TestClient):
    r = client.get("/datasets/nonexistent-id/quality")
    assert r.status_code == 404


def test_summary_endpoint_after_confirm(client: TestClient, sample_csv_bytes: bytes):
    up = client.post("/datasets/upload",
                     files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    preview = up.json()
    mapping = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"] if s["file_column"]}
    client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)

    r = client.get(f"/datasets/{preview['dataset_id']}")
    assert r.status_code == 200
    s = r.json()
    assert s["n_rows"] > 0


def test_upload_xlsx_dispatches_through_openpyxl(client: TestClient, sample_xlsx_bytes: bytes):
    r = client.post(
        "/datasets/upload",
        files={"file": ("data.xlsx", sample_xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["sheet_names"] is not None
    assert preview["selected_sheet"] is not None


def test_duplicate_skus_blocked_at_confirm(client: TestClient, csv_with_duplicates: bytes):
    up = client.post(
        "/datasets/upload",
        files={"file": ("dupes.csv", csv_with_duplicates, "text/csv")},
    )
    preview = up.json()
    mapping = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"] if s["file_column"]}
    r = client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)
    assert r.status_code == 422
    detail = r.json()["detail"]
    codes = {a["code"] for a in detail["assertions"]}
    assert "SKU_DATE_DUPLICATES" in codes
