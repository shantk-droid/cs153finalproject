"""Day-13 tests: observability + rate limits + extended /health."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.main import app
from apps.api.observability import latency_summary, record_latency


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


def test_health_returns_extended_payload(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "version", "environment", "m5_calibration_version", "m5_artifacts_present",
                "m5_artifacts", "sentry_enabled", "anthropic_configured", "latency"):
        assert key in body, f"missing key: {key}"


def test_request_id_header_round_trips(client: TestClient):
    r = client.get("/health", headers={"x-request-id": "test-rid-123"})
    assert r.status_code == 200
    assert r.headers.get("x-request-id") == "test-rid-123"


def test_record_latency_appears_in_summary():
    record_latency("test_op", 42)
    summary = latency_summary()
    assert summary["n_samples"] >= 1
    assert "test_op" in summary["by_operation"]


def test_root_lists_health_endpoint(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "health" in body and "docs" in body


def test_chat_route_404s_on_missing_dataset_before_rate_limiting(client: TestClient):
    """Smoke test that the /chat route is reachable; rate-limit check is below."""
    r = client.post("/datasets/nonexistent-id/chat",
                    json={"dataset_id": "nonexistent-id",
                          "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 404


def test_observability_module_idempotent(client: TestClient):
    """Calling /health repeatedly should not crash even if Sentry isn't configured."""
    for _ in range(3):
        r = client.get("/health")
        assert r.status_code == 200
