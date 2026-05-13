"""Anomaly explainer: detection + LLM narrative + structured judgment + Vega-Lite chart spec.

The detector is deterministic and lives in `anomaly.py`. The LLM produces:
  - a 3-4 sentence narrative `explanation` (free-form)
  - a structured `judgment` dict {cause, confidence, evidence, suggested_adjustment}
    via the forced `submit_anomaly_explanation` tool

Both are returned. The narrative is for human readers; the structured fields let the UI
render distinct cells (e.g., a confidence pill, an action chip) and let downstream code
filter / route by cause.

If the LLM call fails or is disabled, both fall back to deterministic heuristics so the UI
always has something to render.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from apps.api.config import get_settings
from apps.api.db import open_dataset
from apps.api.llm.anomaly import AnomalyEvent, detect_anomalies
from apps.api.llm.loop import run_chat_blocking
from apps.api.llm.prompts import ANOMALY_EXPLAINER_SYSTEM

log = logging.getLogger(__name__)


# US holidays + commerce dates the explainer should be aware of without a tool call.
# Tuple of (month, day, label). Recurring events only — Easter / variable dates omitted.
_FIXED_HOLIDAYS: list[tuple[int, int, str]] = [
    (1, 1, "New Year's Day"),
    (2, 14, "Valentine's Day"),
    (7, 4, "Independence Day"),
    (10, 31, "Halloween"),
    (11, 11, "Veterans Day"),
    (12, 24, "Christmas Eve"),
    (12, 25, "Christmas Day"),
    (12, 31, "New Year's Eve"),
]


def _calendar_context_near(event_date: str, window_days: int = 14) -> list[str]:
    """Return labels of fixed-date holidays within `window_days` of the event.

    Out of scope: floating holidays (Thanksgiving, Memorial Day, Black Friday).
    The fixed list is a coarse but useful prior — the model fills in the rest from training.
    """
    try:
        anchor = datetime.fromisoformat(event_date).date()
    except (ValueError, TypeError):
        return []
    out: list[str] = []
    for month, day, label in _FIXED_HOLIDAYS:
        for year in (anchor.year - 1, anchor.year, anchor.year + 1):
            try:
                holiday = date(year, month, day)
            except ValueError:
                continue
            if abs((holiday - anchor).days) <= window_days:
                out.append(f"{label} ({holiday.isoformat()})")
                break
    # Add month-end / month-start awareness — many promos run around these
    if anchor.day <= 3:
        out.append(f"first {anchor.day} day(s) of {anchor.strftime('%B')}")
    if anchor.day >= 28:
        out.append(f"end of {anchor.strftime('%B')}")
    return out


def _sibling_skus(dataset_id: str, sku_id: str, limit: int = 3) -> list[dict]:
    """Top revenue SKUs in the same category — used to compare event-day behavior."""
    with open_dataset(dataset_id, read_only=True) as conn:
        cat_row = conn.execute(
            "SELECT category FROM panel WHERE sku_id = ? AND category IS NOT NULL LIMIT 1",
            [sku_id.strip().upper()],
        ).fetchone()
        if not cat_row or not cat_row[0]:
            return []
        category = cat_row[0]
        rows = conn.execute(
            """
            SELECT sku_id,
                   COALESCE(SUM(demand * unit_price), SUM(demand)) AS revenue_proxy
            FROM panel
            WHERE category = ?
              AND sku_id != ?
            GROUP BY sku_id
            ORDER BY revenue_proxy DESC
            LIMIT ?
            """,
            [category, sku_id.strip().upper(), limit],
        ).fetchall()
    return [{"sku_id": r[0], "category": category, "revenue_proxy": float(r[1] or 0.0)} for r in rows]


def _fetch_history(dataset_id: str, sku_id: str, last_n: int = 104) -> list[dict]:
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT date, demand FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id.strip().upper()],
        ).fetchdf()
    if df.empty:
        return []
    df = df.tail(last_n)
    return [
        {"date": pd.Timestamp(d).date().isoformat(), "demand": float(v)}
        for d, v in zip(df["date"], df["demand"])
    ]


def _baseline_chart(history: list[dict], target: AnomalyEvent | None) -> dict:
    """Vega-Lite v5 spec: demand line + (optional) vertical rule on the event date."""
    layers: list[dict] = [
        {
            "mark": {"type": "line", "color": "#3b82f6", "strokeWidth": 1.5},
            "encoding": {
                "x": {"field": "date", "type": "temporal", "title": None},
                "y": {"field": "demand", "type": "quantitative", "title": "Demand"},
            },
        }
    ]
    if target is not None:
        layers.append({
            "data": {"values": [{"date": target.date}]},
            "mark": {"type": "rule", "color": "#dc2626", "strokeDash": [4, 3], "strokeWidth": 1.5},
            "encoding": {"x": {"field": "date", "type": "temporal"}},
        })
        layers.append({
            "data": {"values": [{"date": target.date, "demand": target.value, "label": f"z={target.magnitude_z:.1f}"}]},
            "mark": {"type": "point", "color": "#dc2626", "size": 80, "filled": True},
            "encoding": {
                "x": {"field": "date", "type": "temporal"},
                "y": {"field": "demand", "type": "quantitative"},
            },
        })
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container",
        "height": 220,
        "data": {"values": history},
        "layer": layers,
    }


def _heuristic_explanation(target: AnomalyEvent) -> str:
    direction = "spike" if target.direction == "spike" else "drop"
    return (
        f"Detected a {direction} on {target.date}: demand was {target.value:.0f} units vs "
        f"baseline {target.baseline_mean:.0f} ± {target.baseline_std:.0f} "
        f"(robust z = {target.magnitude_z:+.1f}, severity {target.severity}). "
        "Cause unclear from telemetry alone — investigate manually for promotions, supplier issues, "
        "or data-entry mistakes around this date."
    )


def _heuristic_judgment(target: AnomalyEvent, calendar: list[str]) -> dict:
    """Deterministic fallback for the structured fields. Inferred from event + calendar context.

    Confidence is intentionally low — the LLM should beat this when available, and downstream
    UI can show "heuristic only" when source is missing.
    """
    cause = "holiday_or_calendar" if calendar else "unclear"
    direction = "spike" if target.direction == "spike" else "drop"
    evidence = [f"Robust z = {target.magnitude_z:+.1f} on {target.date} ({direction})"]
    if calendar:
        evidence.append(f"Calendar markers within ±2 weeks: {', '.join(calendar)}")
    return {
        "cause": cause,
        "confidence": 0.3 if calendar else 0.15,
        "evidence": evidence,
        "suggested_adjustment": "investigate_manually",
        "source": "heuristic",
    }


def _extract_structured_judgment(tool_calls: list) -> dict | None:
    """Find the `submit_anomaly_explanation` tool call from the agent trace and return its
    args (with source=llm)."""
    for tc in tool_calls:
        if tc.name == "submit_anomaly_explanation" and isinstance(tc.arguments, dict):
            args = tc.arguments
            return {
                "cause": args.get("cause"),
                "confidence": float(args.get("confidence", 0.0)),
                "evidence": list(args.get("evidence") or []),
                "suggested_adjustment": args.get("suggested_adjustment"),
                "source": "llm",
            }
    return None


def explain_anomaly_for_sku(
    dataset_id: str,
    sku_id: str,
    *,
    anchor_date: str | None = None,
    severity_threshold: float = 2.5,
) -> dict:
    """End-to-end: detect events, ask the LLM to explain the top one, return payload.

    Returns both a narrative `explanation` (free-form prose) and a structured `judgment`
    dict {cause, confidence, evidence, suggested_adjustment, source} so the UI can render
    the two side by side."""
    sku_id = sku_id.strip().upper()
    events = detect_anomalies(
        dataset_id, sku_id,
        anchor_date=anchor_date,
        severity_threshold=severity_threshold,
    )
    history = _fetch_history(dataset_id, sku_id)

    if not events:
        return {
            "sku_id": sku_id,
            "detected": [],
            "explanation": (
                "No anomaly above the z=2.5 threshold in the last 200 periods. "
                "Demand is within normal volatility for this SKU."
            ),
            "judgment": None,
            "chart_spec": _baseline_chart(history, None),
            "tool_calls": [],
            "fallback": True,
            "error": None,
        }

    target = events[0]
    settings = get_settings()
    calendar_context = _calendar_context_near(target.date)
    sibling = _sibling_skus(dataset_id, sku_id)

    if not settings.anthropic_api_key:
        return {
            "sku_id": sku_id,
            "detected": [e.to_dict() for e in events[:3]],
            "explanation": _heuristic_explanation(target),
            "judgment": _heuristic_judgment(target, calendar_context),
            "chart_spec": _baseline_chart(history, target),
            "tool_calls": [],
            "fallback": True,
            "error": "ANTHROPIC_API_KEY not configured — using heuristic explanation.",
        }

    payload = json.dumps({
        "sku_id": sku_id,
        "event": target.to_dict(),
        "all_events": [e.to_dict() for e in events[:3]],
        "calendar": calendar_context,
        "sibling_skus": sibling,
    })

    try:
        resp = run_chat_blocking(
            dataset_id,
            [{"role": "user", "content": f"Explain this anomaly event:\n\n{payload}"}],
            system_prompt=ANOMALY_EXPLAINER_SYSTEM,
            tool_subset=[
                "get_sku_details",
                "compare_to_m5",
                "analyze_dataframe",
                "get_forecast",
                "submit_anomaly_explanation",
            ],
            max_iterations=5,
            max_output_tokens=768,
            include_dataset_summary=True,
            enable_thinking=False,
        )
        explanation = resp.text.strip() if resp.text else _heuristic_explanation(target)
        tool_calls = [tc.model_dump() for tc in resp.tool_calls]
        judgment = _extract_structured_judgment(resp.tool_calls)
        if judgment is None:
            judgment = _heuristic_judgment(target, calendar_context)
        return {
            "sku_id": sku_id,
            "detected": [e.to_dict() for e in events[:3]],
            "explanation": explanation,
            "judgment": judgment,
            "calendar_context": calendar_context,
            "chart_spec": _baseline_chart(history, target),
            "tool_calls": tool_calls,
            "fallback": False,
            "error": None,
        }
    except Exception as e:
        log.exception("anomaly explainer LLM call failed")
        return {
            "sku_id": sku_id,
            "detected": [e_.to_dict() for e_ in events[:3]],
            "explanation": _heuristic_explanation(target),
            "judgment": _heuristic_judgment(target, calendar_context),
            "chart_spec": _baseline_chart(history, target),
            "tool_calls": [],
            "fallback": True,
            "error": f"{type(e).__name__}: {e}",
        }
