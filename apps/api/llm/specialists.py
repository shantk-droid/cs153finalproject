"""Specialist sub-agents: Forecaster, Risk, Buyer.

Each is a thin wrapper around `run_chat_blocking()` with a tailored `system_prompt` and
`tool_subset`. The auto_plan.py module is the precedent: it has used this pattern since
day 11.

Specialists are invoked *by the Planner* via the `dispatch_specialist` tool. They never call
each other directly. Their outputs are `SpecialistResult` Pydantic objects — the Planner
threads `summary` + `key_findings` into the next sub-question's user content.

Hard caps per specialist:
- max_iterations = 4 (vs 8 for single-agent — specialists are focused)
- max_output_tokens = 1024
- These are enforced by run_chat_blocking; we just pass the smaller values in.
"""

from __future__ import annotations

import json
from typing import Literal

from apps.api.llm.loop import run_chat_blocking
from apps.api.llm.prompts import (
    BUYER_SYSTEM,
    FORECASTER_SYSTEM,
    PLANNER_SYSTEM,
    RISK_SYSTEM,
)
from apps.api.llm.schemas import SpecialistResult

SPECIALIST_MAX_ITERATIONS = 4
SPECIALIST_MAX_TOKENS = 1024
PLANNER_MAX_ITERATIONS = 8
PLANNER_MAX_TOKENS = 2048


SpecialistName = Literal["forecaster", "risk", "buyer"]

_SPECIALIST_CONFIG: dict[str, dict] = {
    "forecaster": {
        "system_prompt": FORECASTER_SYSTEM,
        "tool_subset": [
            "query_skus",
            "get_sku_details",
            "get_forecast",
            "compare_to_m5",
            "analyze_dataframe",
            "make_chart",
        ],
    },
    "risk": {
        "system_prompt": RISK_SYSTEM,
        "tool_subset": [
            "query_skus",
            "get_sku_details",
            "get_forecast",
            "run_scenario",
            "get_data_quality_report",
            "compare_to_m5",
            "make_chart",
        ],
    },
    "buyer": {
        "system_prompt": BUYER_SYSTEM,
        "tool_subset": [
            "query_skus",
            "get_sku_details",
            "compute_reorder",
            "run_scenario",
            "plan_reorder_week",
            "make_chart",
        ],
    },
}


def _extract_key_findings(text: str) -> list[str]:
    """Cheap bullet-extraction heuristic. The specialist prompts ask for short bullets;
    we scan for lines starting with '-', '*', or digit-period. Falls back to the first
    1-3 sentences if no bullets are found."""
    bullets: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("-", "*", "•")):
            bullets.append(line.lstrip("-*•").strip())
        elif len(line) > 2 and line[0].isdigit() and line[1] in (".", ")"):
            bullets.append(line[2:].strip())
    if bullets:
        return bullets[:8]
    # Fallback: sentence splitter
    sentences = [s.strip() for s in (text or "").replace("\n", " ").split(".") if s.strip()]
    return sentences[:3]


def run_specialist(specialist: SpecialistName, dataset_id: str, sub_question: str, context: str | None = None) -> SpecialistResult:
    """Invoke one specialist on a focused sub-question.

    `context` is an optional preamble — used by the Planner to thread prior findings
    into the specialist's first turn without rebuilding the cached prefix. Kept short
    (≤500 chars in the Planner prompt) so the cache hit on system prompt + dataset
    summary still pays off.
    """
    cfg = _SPECIALIST_CONFIG[specialist]
    user_content = sub_question if not context else f"PRIOR FINDINGS:\n{context}\n\nYOUR TASK:\n{sub_question}"
    response = run_chat_blocking(
        dataset_id=dataset_id,
        user_turns=[{"role": "user", "content": user_content}],
        system_prompt=cfg["system_prompt"],
        tool_subset=cfg["tool_subset"],
        max_iterations=SPECIALIST_MAX_ITERATIONS,
        max_output_tokens=SPECIALIST_MAX_TOKENS,
        enable_thinking=False,
    )
    return SpecialistResult(
        specialist=specialist,
        summary=response.text or "(no summary)",
        key_findings=_extract_key_findings(response.text),
        tool_calls=response.tool_calls,
        usage=response.usage,
        stop_reason=response.stop_reason,
        iterations=response.iterations,
    )


def run_planner(
    dataset_id: str,
    user_question: str,
    *,
    dispatcher,  # callable: (specialist, sub_question, context) -> SpecialistResult
) -> SpecialistResult:
    """Run the Planner agent.

    The `dispatcher` is the orchestrator's invocation function — by passing it in we let
    the orchestrator emit SSE events (`agent_start`, `agent_complete`) per specialist call
    without the Planner having to know about SSE.

    The Planner exposes `dispatch_specialist` and `submit_final_answer` as tools; the
    orchestrator's executors translate `dispatch_specialist` into a synchronous call to
    `dispatcher(...)`. See `_dispatch_specialist_executor` in executors.py.
    """
    # Stash the dispatcher in thread-local state so the executor can find it. threading.local
    # is used (not a module global) to keep concurrent /chat requests in separate threads from
    # racing on the dispatcher — without isolation, request A could end up routing through
    # request B's dispatcher and read B's dataset.
    from apps.api.llm.executors import _clear_active_dispatcher, _set_active_dispatcher
    _set_active_dispatcher(dispatcher)

    try:
        response = run_chat_blocking(
            dataset_id=dataset_id,
            user_turns=[{"role": "user", "content": user_question}],
            system_prompt=PLANNER_SYSTEM,
            tool_subset=[
                "query_skus",
                "get_sku_details",
                "get_aggregate_stats",
                "dispatch_specialist",
                "submit_final_answer",
            ],
            max_iterations=PLANNER_MAX_ITERATIONS,
            max_output_tokens=PLANNER_MAX_TOKENS,
            enable_thinking=False,
        )
    finally:
        _clear_active_dispatcher()

    # Extract the final answer from the most-recent submit_final_answer tool call.
    final_text = response.text
    for tc in response.tool_calls:
        if tc.name == "submit_final_answer" and isinstance(tc.arguments, dict):
            final_text = str(tc.arguments.get("text") or final_text)

    return SpecialistResult(
        specialist="planner",
        summary=final_text or "(planner did not emit a final answer)",
        key_findings=_extract_key_findings(final_text or ""),
        tool_calls=response.tool_calls,
        usage=response.usage,
        stop_reason=response.stop_reason,
        iterations=response.iterations,
    )
