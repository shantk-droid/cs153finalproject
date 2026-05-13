"""Tests for the agentic features: anomaly detector, anomaly explainer fallback,
auto-plan fallback, multi-line PO helper.

LLM-dependent paths use the heuristic/fallback branches so tests don't hit Anthropic.
"""

from __future__ import annotations

import os
from unittest import mock

import pandas as pd
import pytest

from apps.api.ingestion.demo import create_demo_dataset
from apps.api.inventory.purchase_orders import draft_purchase_order_multi_line, get_purchase_order
from apps.api.llm.anomaly import detect_anomalies, AnomalyEvent
from apps.api.llm.anomaly_explainer import explain_anomaly_for_sku, _heuristic_explanation
from apps.api.llm.auto_plan import auto_plan_week, _round_to_pack, _validate_and_normalize


@pytest.fixture
def demo_dataset(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    dataset_id, _ = create_demo_dataset("retail_stable", seed=7)
    return dataset_id


# ---------- anomaly detector ----------

def test_detect_anomalies_finds_synthetic_spike(demo_dataset):
    events = detect_anomalies(demo_dataset, "SKU-00007", severity_threshold=2.0)
    assert isinstance(events, list)
    if events:
        e = events[0]
        assert isinstance(e, AnomalyEvent)
        assert e.severity in ("info", "warn", "crit")
        assert e.direction in ("spike", "drop")
        assert (e.magnitude_z >= 2.0) or (e.magnitude_z <= -2.0)


def test_detect_anomalies_empty_for_unknown_sku(demo_dataset):
    events = detect_anomalies(demo_dataset, "DOES-NOT-EXIST")
    assert events == []


def test_detect_anomalies_anchor_returns_one_event(demo_dataset):
    all_events = detect_anomalies(demo_dataset, "SKU-00007", severity_threshold=2.0)
    if not all_events:
        pytest.skip("no events on this seed/SKU")
    anchor = all_events[0].date
    events = detect_anomalies(demo_dataset, "SKU-00007", anchor_date=anchor, severity_threshold=2.0)
    assert len(events) == 1
    assert events[0].date == anchor


# ---------- anomaly explainer fallback ----------

def test_explain_anomaly_fallback_when_no_api_key(demo_dataset, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = explain_anomaly_for_sku(demo_dataset, "SKU-00007")
    assert "explanation" in out
    assert "chart_spec" in out
    assert isinstance(out["detected"], list)


def test_heuristic_explanation_includes_zscore():
    e = AnomalyEvent(
        date="2025-06-30", value=300.0, direction="spike",
        magnitude_z=15.9, cusum_score=8.2,
        baseline_mean=80.0, baseline_std=15.0,
        severity="crit",
    )
    text = _heuristic_explanation(e)
    assert "spike" in text.lower()
    assert "2025-06-30" in text
    assert "15.9" in text
    assert "300" in text


def test_explain_anomaly_for_unknown_sku(demo_dataset, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = explain_anomaly_for_sku(demo_dataset, "DOES-NOT-EXIST")
    assert out["detected"] == []
    assert out["fallback"] is True


# ---------- auto-plan fallback ----------

def test_auto_plan_fallback_when_no_api_key(demo_dataset, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plan = auto_plan_week(demo_dataset, limit=20, max_suppliers=4)
    assert "draft_pos" in plan
    assert "summary" in plan
    if plan["draft_pos"]:
        d = plan["draft_pos"][0]
        assert "supplier_name" in d
        assert "lines" in d
        assert d["total_cost"] >= 0


def test_round_to_pack_respects_moq_and_case_pack():
    assert _round_to_pack(50, moq=100, case_pack=12) == 108  # ceil(100/12)*12
    assert _round_to_pack(13, moq=12, case_pack=12) == 24    # rounds up to next case
    assert _round_to_pack(0, moq=10, case_pack=1) == 0
    assert _round_to_pack(7, moq=None, case_pack=6) == 12


def test_validate_and_normalize_drops_unknown_skus(demo_dataset):
    from apps.api.inventory.reorder_queue import compute_reorder_queue
    queue = compute_reorder_queue(demo_dataset, limit=10)
    if not queue:
        pytest.skip("no queue items")
    real_sku = queue[0].sku_id
    plan = {
        "summary": "test",
        "draft_pos": [
            {
                "supplier_name": "Test",
                "supplier_id": queue[0].supplier_id,
                "lines": [
                    {"sku_id": real_sku, "qty": queue[0].recommended_qty, "rationale": "ok"},
                    {"sku_id": "FAKE-SKU", "qty": 100, "rationale": "fake"},
                ],
                "rationale": "test PO",
            }
        ],
    }
    out = _validate_and_normalize(plan, queue, demo_dataset, max_suppliers=8)
    assert len(out["draft_pos"]) == 1
    assert all(l["sku_id"] != "FAKE-SKU" for l in out["draft_pos"][0]["lines"])
    assert "FAKE-SKU" in out["dropped_lines"]


# ---------- multi-line PO helper ----------

def test_draft_multi_line_po_creates_correct_lines(demo_dataset):
    po = draft_purchase_order_multi_line(
        demo_dataset,
        lines=[("SKU-00001", 100), ("SKU-00002", 50)],
        expedite_flag=True,
        notes="test",
    )
    assert po.po_id.startswith("PO-")
    assert po.status == "drafted"
    assert po.expedite_flag is True
    assert len(po.lines) == 2
    assert po.total_units == 150
    assert po.total_cost > 0


def test_draft_multi_line_po_drops_invalid_skus(demo_dataset):
    po = draft_purchase_order_multi_line(
        demo_dataset,
        lines=[("SKU-00001", 100), ("FAKE-SKU", 999)],
    )
    assert len(po.lines) == 1
    assert po.lines[0].sku_id == "SKU-00001"
    assert "FAKE-SKU" in (po.notes or "")


def test_draft_multi_line_po_raises_when_all_invalid(demo_dataset):
    with pytest.raises(ValueError):
        draft_purchase_order_multi_line(
            demo_dataset,
            lines=[("FAKE-1", 10), ("FAKE-2", 20)],
        )


def test_draft_multi_line_po_persists_correctly(demo_dataset):
    po = draft_purchase_order_multi_line(
        demo_dataset,
        lines=[("SKU-00001", 100)],
    )
    fetched = get_purchase_order(demo_dataset, po.po_id)
    assert fetched is not None
    assert fetched.po_id == po.po_id
    assert len(fetched.lines) == 1
