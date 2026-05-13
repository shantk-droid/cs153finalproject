"""Adversarial + happy-path tests for the NL-to-query SQL allowlist.

The validator is the critical safety boundary. If it lets through anything dangerous, even
DuckDB's read-only mode might not save us (e.g., information_schema leakage). These tests
pin the allowlist's behavior so future regressions show up immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.llm.executors import ToolExecutionError, execute_tool
from apps.api.llm.nl_query import NlQueryValidationError, validate_sql
from apps.api.llm.tools import all_tool_names
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


# --- happy paths ---


def test_validate_accepts_simple_select():
    sql = "SELECT sku_id, demand FROM panel WHERE demand > 0 LIMIT 10"
    assert validate_sql(sql) == sql


def test_validate_strips_trailing_semicolon():
    sql = "SELECT sku_id FROM panel LIMIT 10;"
    cleaned = validate_sql(sql)
    assert cleaned.endswith("LIMIT 10")
    assert ";" not in cleaned


def test_validate_accepts_aggregate():
    sql = "SELECT supplier, SUM(demand) as total FROM panel GROUP BY supplier ORDER BY total DESC LIMIT 5"
    assert validate_sql(sql) == sql


# --- adversarial inputs (must all reject) ---


def test_validate_rejects_drop_table():
    with pytest.raises(NlQueryValidationError):
        validate_sql("DROP TABLE panel")


def test_validate_rejects_insert():
    with pytest.raises(NlQueryValidationError):
        validate_sql("INSERT INTO panel VALUES (1, 2)")


def test_validate_rejects_delete():
    with pytest.raises(NlQueryValidationError):
        validate_sql("DELETE FROM panel WHERE 1=1")


def test_validate_rejects_attach():
    with pytest.raises(NlQueryValidationError):
        validate_sql("ATTACH '/tmp/x.duckdb' AS x")


def test_validate_rejects_copy_into_file():
    with pytest.raises(NlQueryValidationError):
        validate_sql("COPY panel TO '/tmp/leak.csv'")


def test_validate_rejects_pragma():
    with pytest.raises(NlQueryValidationError):
        validate_sql("PRAGMA database_list")


def test_validate_rejects_multi_statement():
    with pytest.raises(NlQueryValidationError):
        validate_sql("SELECT 1; DROP TABLE panel")


def test_validate_rejects_read_csv():
    with pytest.raises(NlQueryValidationError):
        validate_sql("SELECT * FROM read_csv('/etc/passwd')")


def test_validate_rejects_read_parquet():
    with pytest.raises(NlQueryValidationError):
        validate_sql("SELECT * FROM read_parquet('/tmp/secret.parquet')")


def test_validate_rejects_disallowed_table():
    with pytest.raises(NlQueryValidationError) as exc_info:
        validate_sql("SELECT * FROM secret_table LIMIT 5")
    assert "disallowed" in str(exc_info.value).lower()


def test_validate_rejects_information_schema():
    with pytest.raises(NlQueryValidationError):
        validate_sql("SELECT * FROM information_schema.tables LIMIT 5")


def test_validate_rejects_cte():
    with pytest.raises(NlQueryValidationError):
        validate_sql("WITH x AS (SELECT 1) SELECT * FROM x")


def test_validate_rejects_empty():
    with pytest.raises(NlQueryValidationError):
        validate_sql("")


def test_validate_rejects_unanswerable():
    """The LLM is told to return 'UNANSWERABLE: ...' rather than guess; validator must surface that."""
    with pytest.raises(NlQueryValidationError):
        validate_sql("UNANSWERABLE: schema doesn't contain that column")


def test_validate_rejects_oversize_sql():
    big_sql = "SELECT sku_id FROM panel WHERE sku_id IN (" + ",".join([f"'X{i}'" for i in range(500)]) + ") LIMIT 10"
    with pytest.raises(NlQueryValidationError):
        validate_sql(big_sql)


# --- executor integration ---


def test_nl_to_query_falls_back_without_api_key(monkeypatch: pytest.MonkeyPatch, dataset_id: str):
    """No API key → executor returns an error block, NOT a raised exception. The agent layer
    sees `{error: ...}` and can recover."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    out = execute_tool("nl_to_query", dataset_id, {"question": "top 5 SKUs by demand"})
    assert "error" in out
    assert "ANTHROPIC_API_KEY" in out["error"]


def test_nl_to_query_requires_question(dataset_id: str):
    with pytest.raises(ToolExecutionError):
        execute_tool("nl_to_query", dataset_id, {})


def test_nl_to_query_rejects_long_question(dataset_id: str):
    long_q = "a" * 1000
    with pytest.raises(ToolExecutionError):
        execute_tool("nl_to_query", dataset_id, {"question": long_q})


def test_nl_to_query_registered_in_tool_registry():
    assert "nl_to_query" in all_tool_names()
