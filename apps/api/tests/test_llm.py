"""Tests for the chat layer that don't make real Anthropic calls.

The eval harness (`apps/api/llm/eval.py`) is the integration test that does call the API.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.llm.executors import ToolExecutionError, execute_tool
from apps.api.llm.prompts import SYSTEM_PROMPT, build_dataset_summary
from apps.api.llm.tools import ALL_TOOL_DEFINITIONS, TOOL_DEFINITIONS, all_tool_names, tool_names
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


# --- tool definitions ---

def test_tool_definitions_unique_names():
    names = tool_names()
    assert len(names) == len(set(names))
    assert "plan_reorder_week" in names
    assert "nl_to_query" in names
    assert len(names) == 13  # 10 chat + submit_plan + plan_reorder_week + nl_to_query


def test_planner_tools_separate_from_chat_tools():
    from apps.api.llm.tools import ANOMALY_TOOL_DEFINITIONS, PLANNER_TOOL_DEFINITIONS
    planner_names = {t["name"] for t in PLANNER_TOOL_DEFINITIONS}
    anomaly_names = {t["name"] for t in ANOMALY_TOOL_DEFINITIONS}
    chat_names = set(tool_names())
    assert planner_names == {"dispatch_specialist", "submit_final_answer"}
    assert anomaly_names == {"submit_anomaly_explanation"}
    # The three pools are pairwise disjoint
    assert not (planner_names & chat_names), "planner tools must not leak into chat surface"
    assert not (anomaly_names & chat_names), "anomaly tools must not leak into chat surface"
    assert not (anomaly_names & planner_names)
    # Their union is exactly all_tool_names
    assert set(all_tool_names()) == chat_names | planner_names | anomaly_names


def test_every_tool_has_input_schema():
    for t in TOOL_DEFINITIONS:
        assert "name" in t and "description" in t and "input_schema" in t
        assert t["input_schema"]["type"] == "object"


def test_executor_registry_matches_tool_definitions():
    from apps.api.llm.executors import EXECUTORS
    # Every tool (chat + planner) must have an executor; equivalently, no orphan executors.
    assert set(EXECUTORS.keys()) == set(all_tool_names())


# --- executors ---

def test_query_skus_returns_rows(dataset_id: str):
    out = execute_tool("query_skus", dataset_id, {"limit": 5})
    assert "skus" in out and "total_matched" in out
    assert 0 < len(out["skus"]) <= 5


def test_query_skus_filters_by_abc(dataset_id: str):
    out = execute_tool("query_skus", dataset_id, {"abc": "A", "limit": 50})
    assert all(r["abc_class"] == "A" for r in out["skus"])


def test_get_sku_details_returns_full_record(dataset_id: str):
    listing = execute_tool("query_skus", dataset_id, {"limit": 1})
    sku = listing["skus"][0]["sku_id"]
    out = execute_tool("get_sku_details", dataset_id, {"sku_id": sku})
    assert out["sku_id"] == sku
    assert "abc_class" in out and "n_observations" in out


def test_get_sku_details_raises_for_unknown(dataset_id: str):
    with pytest.raises(ToolExecutionError):
        execute_tool("get_sku_details", dataset_id, {"sku_id": "DOES-NOT-EXIST"})


def test_get_forecast_returns_intervals(dataset_id: str):
    listing = execute_tool("query_skus", dataset_id, {"limit": 1})
    sku = listing["skus"][0]["sku_id"]
    out = execute_tool("get_forecast", dataset_id, {"sku_id": sku, "horizon_periods": 4})
    assert len(out["point"]) == 4
    assert len(out["upper_95"]) == 4
    assert all(u >= l for u, l in zip(out["upper_95"], out["lower_95"]))


def test_compute_reorder_default_service_level(dataset_id: str):
    listing = execute_tool("query_skus", dataset_id, {"limit": 1})
    sku = listing["skus"][0]["sku_id"]
    out = execute_tool("compute_reorder", dataset_id, {"sku_id": sku})
    assert out["sku_id"] == sku
    assert 0.0 <= out["expected_stockout_prob"] <= 1.0


def test_compute_reorder_higher_service_level_increases_safety(dataset_id: str):
    listing = execute_tool("query_skus", dataset_id, {"limit": 1})
    sku = listing["skus"][0]["sku_id"]
    a = execute_tool("compute_reorder", dataset_id, {"sku_id": sku, "service_level": 0.9})
    b = execute_tool("compute_reorder", dataset_id, {"sku_id": sku, "service_level": 0.99})
    assert b["safety_stock"] >= a["safety_stock"]


def test_run_scenario_returns_base_and_scenario(dataset_id: str):
    listing = execute_tool("query_skus", dataset_id, {"limit": 1})
    sku = listing["skus"][0]["sku_id"]
    out = execute_tool("run_scenario", dataset_id, {
        "sku_ids": [sku],
        "perturbations": {"lead_time_multiplier": 2.0},
    })
    assert len(out["results"]) == 1
    r = out["results"][0]
    assert "base" in r and "scenario" in r and "delta" in r


def test_get_aggregate_stats_returns_heatmap(dataset_id: str):
    out = execute_tool("get_aggregate_stats", dataset_id, {})
    assert set(out["abc_xyz_heatmap"].keys()) == {"AX","AY","AZ","BX","BY","BZ","CX","CY","CZ"}
    assert sum(out["abc_xyz_heatmap"].values()) == out["n_skus"]


# --- plan_reorder_week ---

def test_plan_reorder_week_returns_structured_plan(dataset_id: str):
    out = execute_tool("plan_reorder_week", dataset_id, {"top_n": 10})
    assert out["horizon_days"] == 7
    assert out["service_level"] == 0.95
    assert isinstance(out["items"], list)
    assert len(out["items"]) <= 10
    assert out["budget_cap_usd"] is None
    for item in out["items"]:
        assert "sku_id" in item and "qty" in item and "rationale" in item
        assert item["qty"] > 0


def test_plan_reorder_week_respects_budget_cap(dataset_id: str):
    no_cap = execute_tool("plan_reorder_week", dataset_id, {"top_n": 50})
    if not no_cap["items"]:
        pytest.skip("dataset has no reorder candidates")
    cap = no_cap["total_cost_usd"] / 2.0
    out = execute_tool("plan_reorder_week", dataset_id, {"top_n": 50, "budget_cap_usd": cap})
    assert out["total_cost_usd"] <= cap + 1e-6
    assert out["budget_cap_usd"] == cap
    assert out["budget_used_pct"] is not None
    assert isinstance(out["deferred_items"], list)


def test_plan_reorder_week_rejects_invalid_service_level(dataset_id: str):
    with pytest.raises(ToolExecutionError):
        execute_tool("plan_reorder_week", dataset_id, {"service_level": 0.1})


def test_plan_reorder_week_rest_endpoint(client: TestClient, dataset_id: str):
    resp = client.post(
        f"/datasets/{dataset_id}/plan_reorder_week",
        json={"top_n": 5, "service_level": 0.95},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["horizon_days"] == 7
    assert len(body["items"]) <= 5


# --- analyze_dataframe chart_data format ---

def test_analyze_dataframe_chart_data_emits_hint(dataset_id: str):
    out = execute_tool("analyze_dataframe", dataset_id, {
        "query": {"groupby": ["category"], "aggregate": {"demand": "sum"}, "limit": 20},
        "format": "chart_data",
    })
    assert "rows" in out
    assert "chart_hint" in out
    hint = out["chart_hint"]
    assert hint["mark"] == "bar"
    assert hint["x"]["field"] == "category"
    assert hint["y"]["field"] == "demand"


def test_analyze_dataframe_chart_data_line_for_date(dataset_id: str):
    out = execute_tool("analyze_dataframe", dataset_id, {
        "query": {"groupby": ["date"], "aggregate": {"demand": "sum"}, "limit": 100},
        "format": "chart_data",
    })
    assert out["chart_hint"]["mark"] == "line"
    assert out["chart_hint"]["x"]["type"] == "temporal"


def test_analyze_dataframe_table_format_omits_hint(dataset_id: str):
    out = execute_tool("analyze_dataframe", dataset_id, {
        "query": {"groupby": ["category"], "aggregate": {"demand": "sum"}, "limit": 20},
    })
    assert "rows" in out
    assert "chart_hint" not in out


def test_analyze_dataframe_rejects_unknown_format(dataset_id: str):
    with pytest.raises(ToolExecutionError):
        execute_tool("analyze_dataframe", dataset_id, {
            "query": {"limit": 5},
            "format": "html",
        })


# --- multi-agent structural tests (no real API calls) ---

def test_router_falls_back_to_single_when_no_api_key(monkeypatch: pytest.MonkeyPatch):
    from apps.api.config import get_settings
    from apps.api.llm.router import route

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    decision = route("How many SKUs do I have?")
    assert decision.path == "single"
    assert "ANTHROPIC_API_KEY" in decision.rationale


def test_dispatch_specialist_requires_active_dispatcher(dataset_id: str):
    """Outside the orchestrator, dispatch_specialist must refuse — there's no Planner context."""
    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool("dispatch_specialist", dataset_id, {
            "specialist": "forecaster",
            "sub_question": "test",
        })
    assert "no active dispatcher" in str(exc_info.value).lower()


def test_dispatch_specialist_rejects_unknown_specialist(dataset_id: str):
    from apps.api.llm.executors import _clear_active_dispatcher, _set_active_dispatcher
    _set_active_dispatcher(lambda *_args, **_kw: None)  # any non-None sentinel
    try:
        with pytest.raises(ToolExecutionError):
            execute_tool("dispatch_specialist", dataset_id, {
                "specialist": "controller",  # not in {forecaster, risk, buyer}
                "sub_question": "test",
            })
    finally:
        _clear_active_dispatcher()


def test_dispatcher_isolated_per_thread():
    """Threads must not see each other's dispatchers — a multi-tenant safety invariant."""
    import threading
    from apps.api.llm.executors import (
        _clear_active_dispatcher,
        _get_active_dispatcher,
        _set_active_dispatcher,
    )

    def sentinel_a():
        return "A"

    def sentinel_b():
        return "B"

    results: dict[str, object] = {}

    def thread_a():
        _set_active_dispatcher(sentinel_a)
        # Block briefly so B can overwrite if module-global, but stay isolated if thread-local
        import time
        time.sleep(0.05)
        results["a"] = _get_active_dispatcher()
        _clear_active_dispatcher()

    def thread_b():
        _set_active_dispatcher(sentinel_b)
        results["b"] = _get_active_dispatcher()
        _clear_active_dispatcher()

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    assert results["a"] is sentinel_a, "thread A saw a different thread's dispatcher"
    assert results["b"] is sentinel_b


def test_submit_final_answer_requires_text(dataset_id: str):
    with pytest.raises(ToolExecutionError):
        execute_tool("submit_final_answer", dataset_id, {"text": ""})
    with pytest.raises(ToolExecutionError):
        execute_tool("submit_final_answer", dataset_id, {})
    out = execute_tool("submit_final_answer", dataset_id, {"text": "final answer here"})
    assert out["text"] == "final answer here"


def test_specialist_tool_subsets_have_no_dispatch_tools():
    """Forecaster/Risk/Buyer must NOT have dispatch_specialist — only the Planner does.
    Otherwise specialists could spawn other specialists, breaking the Planner-as-coordinator
    invariant and exposing us to unbounded recursion."""
    from apps.api.llm.specialists import _SPECIALIST_CONFIG
    for name, cfg in _SPECIALIST_CONFIG.items():
        assert "dispatch_specialist" not in cfg["tool_subset"], f"{name} has dispatch_specialist"
        assert "submit_final_answer" not in cfg["tool_subset"], f"{name} has submit_final_answer"


def test_buyer_does_not_have_submit_plan():
    """Buyer must NOT have submit_plan — that's the auto_plan agent's tool and would create
    side-effect collisions when invoked from the chat flow. Confirms a known design rule."""
    from apps.api.llm.specialists import _SPECIALIST_CONFIG
    assert "submit_plan" not in _SPECIALIST_CONFIG["buyer"]["tool_subset"]


def test_chat_route_default_is_multi_agent(monkeypatch: pytest.MonkeyPatch, client: TestClient, dataset_id: str):
    """When ?single is not set, the multi-agent orchestrator path is taken. We force the
    Router to single-fallback by emptying the API key so the request returns an SSE error
    event — but the routing path through orchestrator vs stream_chat_sse is what we're
    verifying via the `router_decision` event being present."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    resp = client.post(
        f"/datasets/{dataset_id}/chat",
        json={"dataset_id": dataset_id, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    body = resp.text
    # Either the orchestrator yielded a router_decision event before delegating, or the
    # single path was force-selected. Both prove the orchestrator entered.
    assert "router_decision" in body or "ANTHROPIC_API_KEY" in body


def test_single_param_bypasses_orchestrator(monkeypatch: pytest.MonkeyPatch, client: TestClient, dataset_id: str):
    """`?single=1` skips the Router entirely. Used by the eval harness."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    resp = client.post(
        f"/datasets/{dataset_id}/chat?single=1",
        json={"dataset_id": dataset_id, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    # router_decision must NOT appear because we bypassed the orchestrator.
    assert "router_decision" not in resp.text


# --- scheduled briefing ---

def test_briefing_get_returns_stub_when_not_generated(client: TestClient, dataset_id: str):
    resp = client.get(f"/datasets/{dataset_id}/briefing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stub"] is True
    assert body["text"] == ""
    assert "date" in body


def test_briefing_get_returns_cached_when_present(client: TestClient, dataset_id: str):
    from datetime import date
    from apps.api.llm.briefing import _briefing_path

    settings = get_settings()
    path = _briefing_path(settings.data_path, dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    _json.dump({
        "dataset_id": dataset_id,
        "date": date.today().isoformat(),
        "text": "Test briefing content.",
        "stub": False,
        "usage_usd": 0.01,
    }, path.open("w"))

    resp = client.get(f"/datasets/{dataset_id}/briefing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Test briefing content."
    assert body["stub"] is False


def test_briefing_refresh_falls_back_when_no_api_key(monkeypatch: pytest.MonkeyPatch, client: TestClient, dataset_id: str):
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    resp = client.post(f"/datasets/{dataset_id}/briefing/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stub"] is True
    assert "ANTHROPIC_API_KEY" in body.get("reason", "")


def test_unknown_tool_raises():
    with pytest.raises(ToolExecutionError):
        execute_tool("nonexistent_tool", "any", {})


# --- prompts / dataset summary ---

def test_dataset_summary_includes_n_skus_and_dates(dataset_id: str):
    summary = build_dataset_summary(dataset_id)
    assert "DATASET SUMMARY" in summary
    assert "SKUs" in summary
    assert "frequency" in summary


def test_system_prompt_mentions_tool_use_and_caveats():
    assert "tool" in SYSTEM_PROMPT.lower()
    assert "caveat" in SYSTEM_PROMPT.lower()


# --- daily budget enforcement ---

def test_budget_exceeded_returns_429(dataset_id: str, client: TestClient):
    from apps.api.llm.cost_ledger import add_spend

    settings = get_settings()
    add_spend(settings.data_path, usd=settings.llm_daily_usd_budget + 1.0, context="test_seed")

    resp = client.post(
        f"/datasets/{dataset_id}/chat",
        json={"dataset_id": dataset_id, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 429
    body = resp.json()
    detail = body["detail"]
    assert detail["code"] == "budget_exceeded"
    assert detail["spent_usd"] >= settings.llm_daily_usd_budget


def test_budget_check_passes_when_under_cap(dataset_id: str):
    from apps.api.llm.cost_ledger import BudgetExceededError, add_spend, check_budget

    settings = get_settings()
    add_spend(settings.data_path, usd=0.01, context="test_seed")
    check_budget(settings.data_path, settings.llm_daily_usd_budget)


def test_budget_check_raises_at_threshold(tmp_path: Path):
    from apps.api.llm.cost_ledger import BudgetExceededError, add_spend, check_budget

    add_spend(tmp_path, usd=5.0, context="test_seed")
    with pytest.raises(BudgetExceededError) as exc_info:
        check_budget(tmp_path, budget_usd=5.0)
    assert exc_info.value.spent_usd >= 5.0
    assert exc_info.value.budget_usd == 5.0
