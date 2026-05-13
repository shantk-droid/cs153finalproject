"""Weekly auto-plan agent.

Inputs the pre-computed reorder queue. The LLM groups by supplier and writes
a per-PO rationale. Final output is forced through the `submit_plan` tool so
we get structured JSON. We then validate against the panel + suppliers tables
and re-look-up unit_cost ourselves — the LLM is never trusted with prices.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

import pandas as pd

from apps.api.config import get_settings
from apps.api.db import open_dataset
from apps.api.inventory.reorder_queue import compute_reorder_queue
from apps.api.llm.loop import run_chat_blocking
from apps.api.llm.prompts import AUTO_PLAN_SYSTEM

log = logging.getLogger(__name__)


def _round_to_pack(qty: float, moq: float | None, case_pack: float | None) -> float:
    q = max(0.0, float(qty))
    if case_pack and case_pack > 0:
        q = math.ceil(q / case_pack) * case_pack
    if moq and q > 0 and q < moq:
        q = moq
        # MOQ floor may not align with case-pack — round up again so the order
        # is both ≥ MOQ AND a case-pack multiple.
        if case_pack and case_pack > 0 and q % case_pack != 0:
            q = math.ceil(q / case_pack) * case_pack
    return float(q)


def _supplier_lookup(dataset_id: str) -> dict[str, dict]:
    with open_dataset(dataset_id, read_only=True) as conn:
        suppliers = conn.execute("SELECT * FROM suppliers").fetchdf()
    if suppliers.empty:
        return {}
    out: dict[str, dict] = {}
    for _, row in suppliers.iterrows():
        rec = row.to_dict()
        out[str(rec["supplier_id"])] = rec
        if rec.get("name"):
            out[str(rec["name"])] = rec
    return out


def _panel_unit_costs(dataset_id: str, sku_ids: list[str]) -> dict[str, float | None]:
    if not sku_ids:
        return {}
    placeholders = ",".join("?" for _ in sku_ids)
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            f"SELECT sku_id, unit_cost FROM panel WHERE sku_id IN ({placeholders}) "
            "AND unit_cost IS NOT NULL ORDER BY date DESC",
            sku_ids,
        ).fetchdf()
    if df.empty:
        return {sid: None for sid in sku_ids}
    out: dict[str, float | None] = {sid: None for sid in sku_ids}
    seen: set[str] = set()
    for _, row in df.iterrows():
        sid = str(row["sku_id"])
        if sid in seen:
            continue
        out[sid] = float(row["unit_cost"]) if pd.notna(row["unit_cost"]) else None
        seen.add(sid)
    return out


def _fallback_plan(queue: list, dataset_id: str, error: str | None = None) -> dict:
    """Group the queue by supplier deterministically. No LLM."""
    by_sup: dict[str, list] = {}
    for item in queue:
        key = item.supplier_id or item.supplier_name or "UNKNOWN"
        by_sup.setdefault(key, []).append(item)

    sup_lookup = _supplier_lookup(dataset_id)
    drafts: list[dict] = []
    for sup_key, items in list(by_sup.items())[:8]:
        items.sort(key=lambda i: i.revenue_at_risk, reverse=True)
        top = items[0]
        sup_meta = sup_lookup.get(sup_key) or {}
        rationale = (
            f"Top stockout risk on this supplier is {top.sku_id} at "
            f"{top.stockout_prob*100:.0f}% (≈${top.revenue_at_risk:.0f} at risk). "
            f"Auto-grouped fallback — review before placing."
        )
        lines = []
        for it in items[:15]:
            lines.append({
                "sku_id": it.sku_id,
                "qty": float(it.recommended_qty),
                "unit_cost": float(it.unit_cost) if it.unit_cost is not None else None,
                "rationale": (
                    f"stockout_prob={it.stockout_prob*100:.0f}%, "
                    f"on_hand={it.on_hand if it.on_hand is not None else '—'}"
                ),
            })
        total_cost = sum((l["qty"] * (l["unit_cost"] or 0.0)) for l in lines)
        drafts.append({
            "supplier_name": top.supplier_name or sup_key,
            "supplier_id": top.supplier_id or sup_meta.get("supplier_id"),
            "lines": lines,
            "expedite": any(it.expedite_flag for it in items),
            "joint_replen_group": top.joint_replen_group,
            "rationale": rationale,
            "total_cost": float(total_cost),
        })
    return {
        "summary": (
            f"Auto-fallback plan: {len(drafts)} POs covering {sum(len(d['lines']) for d in drafts)} SKUs. "
            f"LLM agent unavailable — review carefully before accepting."
        ),
        "draft_pos": drafts,
        "fallback": True,
        "error": error,
        "tool_calls": [],
    }


def _extract_submit_plan(resp) -> dict | None:
    for tc in resp.tool_calls:
        if tc.name == "submit_plan":
            return tc.arguments
    return None


def _validate_and_normalize(
    plan: dict,
    queue: list,
    dataset_id: str,
    *,
    max_suppliers: int,
) -> dict:
    """Cross-check every line against the panel + queue. LLM cannot inject bad data."""
    queue_by_sku = {it.sku_id: it for it in queue}
    sup_lookup = _supplier_lookup(dataset_id)

    drafts_in = plan.get("draft_pos") or []
    drafts_out: list[dict] = []
    dropped_lines: list[str] = []

    for draft in drafts_in[:max_suppliers]:
        if not isinstance(draft, dict):
            continue
        lines_in = draft.get("lines") or []
        sku_ids_in_draft = [str(l.get("sku_id", "")).strip().upper() for l in lines_in if isinstance(l, dict)]
        unit_costs = _panel_unit_costs(dataset_id, sku_ids_in_draft)

        sup_id = draft.get("supplier_id")
        sup_name = draft.get("supplier_name")
        sup_meta = (sup_lookup.get(str(sup_id)) if sup_id else None) or (sup_lookup.get(str(sup_name)) if sup_name else None)
        if sup_meta:
            sup_id = sup_meta.get("supplier_id") or sup_id
            sup_name = sup_meta.get("name") or sup_name

        out_lines: list[dict] = []
        for line in lines_in:
            if not isinstance(line, dict):
                continue
            sku_id = str(line.get("sku_id", "")).strip().upper()
            if not sku_id or sku_id not in queue_by_sku:
                dropped_lines.append(sku_id or "<empty>")
                continue
            qit = queue_by_sku[sku_id]
            qty = _round_to_pack(line.get("qty", qit.recommended_qty), qit.moq, qit.case_pack)
            if qty <= 0:
                dropped_lines.append(sku_id)
                continue
            uc = unit_costs.get(sku_id)
            if uc is None:
                uc = qit.unit_cost
            out_lines.append({
                "sku_id": sku_id,
                "qty": float(qty),
                "unit_cost": float(uc) if uc is not None else None,
                "rationale": str(line.get("rationale") or "")[:240],
            })
        if not out_lines:
            continue

        total_cost = sum(l["qty"] * (l["unit_cost"] or 0.0) for l in out_lines)
        expedite = bool(draft.get("expedite") or any(queue_by_sku[l["sku_id"]].expedite_flag for l in out_lines))
        rationale = str(draft.get("rationale") or "")[:280]
        drafts_out.append({
            "supplier_id": sup_id,
            "supplier_name": sup_name or "Unknown supplier",
            "lines": out_lines[:15],
            "expedite": expedite,
            "joint_replen_group": queue_by_sku[out_lines[0]["sku_id"]].joint_replen_group,
            "rationale": rationale or "Reorder cluster — see lines.",
            "total_cost": float(total_cost),
        })

    summary = str(plan.get("summary") or "").strip()
    if not summary:
        summary = f"{len(drafts_out)} draft POs covering {sum(len(d['lines']) for d in drafts_out)} SKUs."
    if dropped_lines:
        summary += f" ({len(dropped_lines)} invalid line(s) dropped during validation.)"

    return {
        "summary": summary,
        "draft_pos": drafts_out,
        "fallback": False,
        "error": None,
        "dropped_lines": dropped_lines,
    }


def auto_plan_week(
    dataset_id: str,
    *,
    limit: int = 50,
    max_suppliers: int = 8,
) -> dict:
    """Compute the queue, ask the LLM to group + rationalize, validate."""
    queue = compute_reorder_queue(dataset_id, limit=limit, days_of_cover_threshold=30.0)
    if not queue:
        return {
            "summary": "No SKUs need reordering this week — inventory levels are healthy.",
            "draft_pos": [],
            "fallback": False,
            "error": None,
            "tool_calls": [],
        }

    settings = get_settings()
    if not settings.anthropic_api_key:
        out = _fallback_plan(queue, dataset_id, error="ANTHROPIC_API_KEY not configured.")
        return out

    queue_payload = [
        {
            "sku_id": i.sku_id,
            "supplier": i.supplier_name,
            "supplier_id": i.supplier_id,
            "recommended_qty": i.recommended_qty,
            "unit_cost": i.unit_cost,
            "stockout_prob": round(i.stockout_prob, 3),
            "revenue_at_risk": round(i.revenue_at_risk, 0),
            "expedite_flag": i.expedite_flag,
            "moq": i.moq,
            "case_pack": i.case_pack,
            "joint_replen_group": i.joint_replen_group,
        }
        for i in queue[:limit]
    ]

    user_payload = json.dumps({
        "queue": queue_payload,
        "instructions": (
            f"Group these into ≤{max_suppliers} draft POs (one per supplier_id). "
            "Write a one-sentence rationale per PO referencing the highest-revenue line. "
            "Call submit_plan exactly once with your final list."
        ),
    })

    try:
        resp = run_chat_blocking(
            dataset_id,
            [{"role": "user", "content": f"Plan this week's POs:\n\n{user_payload}"}],
            system_prompt=AUTO_PLAN_SYSTEM,
            tool_subset=["query_skus", "compute_reorder", "get_aggregate_stats", "submit_plan"],
            tool_choice={"type": "any"},
            max_iterations=4,
            max_output_tokens=2048,
            include_dataset_summary=True,
            enable_thinking=False,
        )
        plan = _extract_submit_plan(resp)
        if not plan:
            log.warning("auto_plan: submit_plan not called; falling back")
            out = _fallback_plan(queue, dataset_id, error="LLM did not call submit_plan.")
            out["tool_calls"] = [tc.model_dump() for tc in resp.tool_calls]
            return out

        normalized = _validate_and_normalize(plan, queue, dataset_id, max_suppliers=max_suppliers)
        normalized["tool_calls"] = [tc.model_dump() for tc in resp.tool_calls]
        return normalized
    except Exception as e:
        log.exception("auto_plan LLM call failed")
        return _fallback_plan(queue, dataset_id, error=f"{type(e).__name__}: {e}")
