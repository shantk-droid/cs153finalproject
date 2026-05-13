"""Day-10 tests: sandbox + new tools."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.llm.executors import ToolExecutionError, execute_tool
from apps.api.llm.sandbox import SandboxQueryError, execute_query
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


# --- sandbox ---

def test_sandbox_filter_only(sample_panel: pd.DataFrame):
    out = execute_query(sample_panel, {"filter": [{"col": "demand", "op": ">=", "value": 50}], "limit": 5})
    assert len(out["rows"]) <= 5
    assert all(r["demand"] >= 50 for r in out["rows"])


def test_sandbox_groupby_aggregate(sample_panel: pd.DataFrame):
    out = execute_query(sample_panel, {
        "groupby": ["category"],
        "aggregate": {"demand": "sum", "sku_id": "nunique"},
        "sort_by": "demand",
    })
    assert len(out["rows"]) > 0
    assert "category" in out["rows"][0]


def test_sandbox_rejects_unknown_column(sample_panel: pd.DataFrame):
    with pytest.raises(SandboxQueryError):
        execute_query(sample_panel, {"filter": [{"col": "evil_col", "op": "==", "value": 1}]})


def test_sandbox_rejects_unknown_op(sample_panel: pd.DataFrame):
    with pytest.raises(SandboxQueryError):
        execute_query(sample_panel, {"filter": [{"col": "demand", "op": "exec", "value": 1}]})


def test_sandbox_rejects_unknown_aggregate(sample_panel: pd.DataFrame):
    with pytest.raises(SandboxQueryError):
        execute_query(sample_panel, {"aggregate": {"demand": "drop_table"}})


def test_sandbox_limit_clamp(sample_panel: pd.DataFrame):
    with pytest.raises(SandboxQueryError):
        execute_query(sample_panel, {"limit": 100000})


# --- Day-10 tool executors ---

def test_get_data_quality_report_tool(dataset_id: str):
    out = execute_tool("get_data_quality_report", dataset_id, {})
    assert "composite_score" in out
    assert "components" in out
    component_names = {c["name"] for c in out["components"]}
    assert component_names == {"completeness", "plausibility", "distribution_profile", "history_depth", "stationarity"}


def test_compare_to_m5_tool(dataset_id: str):
    """compare_to_m5 should work even when category doesn't match M5 — falls back to _default."""
    listing = execute_tool("query_skus", dataset_id, {"limit": 1})
    sku = listing["skus"][0]["sku_id"]
    out = execute_tool("compare_to_m5", dataset_id, {"sku_id": sku})
    assert out["sku_id"] == sku
    assert "comparisons" in out


def test_analyze_dataframe_tool_groupby(dataset_id: str):
    out = execute_tool("analyze_dataframe", dataset_id, {
        "query": {
            "groupby": ["category"],
            "aggregate": {"demand": "sum"},
            "sort_by": "demand",
            "limit": 10,
        }
    })
    assert "rows" in out
    assert len(out["rows"]) > 0
    assert "category" in out["rows"][0]


def test_make_chart_passes_through_spec(dataset_id: str):
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": [{"a": 1, "b": 2}]},
        "mark": "bar",
        "encoding": {"x": {"field": "a"}, "y": {"field": "b"}},
    }
    out = execute_tool("make_chart", dataset_id, {"spec": spec, "title": "Test chart"})
    assert out["spec"] == spec
    assert out["_render"] == "vega-lite"


def test_analyze_dataframe_rejects_invalid_query(dataset_id: str):
    with pytest.raises(ToolExecutionError):
        execute_tool("analyze_dataframe", dataset_id, {"query": {"filter": [{"col": "evil", "op": "==", "value": 1}]}})
