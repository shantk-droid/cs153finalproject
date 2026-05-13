"""Tests for the LLM-narrated dashboard tour."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
def dataset_id(client: TestClient, sample_csv_bytes: bytes) -> str:
    up = client.post("/datasets/upload", files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    preview = up.json()
    mapping = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"] if s["file_column"]}
    client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)
    return preview["dataset_id"]


def test_tour_returns_heuristic_when_no_api_key(monkeypatch: pytest.MonkeyPatch, client: TestClient, dataset_id: str):
    """Without an API key, the tour falls back to the canned 4-step heuristic so the modal
    always renders. Source field must be 'heuristic'."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    resp = client.get(f"/datasets/{dataset_id}/tour")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "heuristic"
    assert len(body["steps"]) == 4
    for step in body["steps"]:
        assert "title" in step and "body" in step and "route" in step
        # routes must use {id} placeholder so the frontend substitutes
        assert "{id}" in step["route"] or dataset_id in step["route"]


def test_tour_cache_hit_returns_cached(monkeypatch: pytest.MonkeyPatch, client: TestClient, dataset_id: str):
    """A pre-existing cache file is returned verbatim, no LLM call. We seed a sentinel and
    confirm it's surfaced unchanged."""
    settings = get_settings()
    from apps.api.llm.tour import _tour_path

    path = _tour_path(dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    sentinel = {
        "dataset_id": dataset_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "sentinel-test",
        "steps": [
            {"title": "Cached step 1", "body": "First.", "route": "/dashboard/{id}"},
            {"title": "Cached step 2", "body": "Second.", "route": "/dashboard/{id}/forecasts"},
            {"title": "Cached step 3", "body": "Third.", "route": "/dashboard/{id}/reorder"},
            {"title": "Cached step 4", "body": "Fourth.", "route": "/dashboard/{id}/quality"},
        ],
        "usage_usd": 0.0,
    }
    path.write_text(json.dumps(sentinel))

    # Force no-API-key so any cache miss would land on heuristic, not LLM.
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    resp = client.get(f"/datasets/{dataset_id}/tour")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "sentinel-test"
    assert body["steps"][0]["title"] == "Cached step 1"


def test_tour_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch, client: TestClient, dataset_id: str):
    """A cache file older than TTL is treated as stale → regenerate path runs."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    from apps.api.llm.tour import _tour_path

    path = _tour_path(dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Set a 60-day-old cache; TTL is 30 days
    stale_iso = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    sentinel = {
        "dataset_id": dataset_id,
        "generated_at_utc": stale_iso,
        "source": "old-sentinel",
        "steps": [{"title": "stale"}] * 4,
        "usage_usd": 0.0,
    }
    path.write_text(json.dumps(sentinel))

    resp = client.get(f"/datasets/{dataset_id}/tour")
    body = resp.json()
    # Should NOT see the stale sentinel — it expired
    assert body["source"] != "old-sentinel"
    assert body["source"] == "heuristic"


def test_tour_404_for_missing_dataset(client: TestClient):
    resp = client.get("/datasets/does-not-exist/tour")
    assert resp.status_code == 404
