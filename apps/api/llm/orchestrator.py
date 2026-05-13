"""Multi-agent orchestrator.

Top-level coordinator that runs Router → Planner → specialists, emitting SSE events for the
frontend. The single-agent path is left untouched (`stream_chat_sse` in loop.py) — this module
adds a parallel path for multi-step decompositions.

Architecture (per the approved plan):
- Router classifies the user's question. If `path == "single"`, we just delegate to the
  existing `stream_chat_sse` and the rest of this module is a no-op.
- If `path == "multi"`, we kick off the Planner in a background thread. The Planner is sync
  (uses `run_chat_blocking`) so we use an asyncio.Queue to bridge sync → async for SSE.
  Each `dispatch_specialist` tool call invokes a specialist sub-loop synchronously; before
  and after, we push agent_start / agent_complete events onto the queue. The SSE generator
  drains the queue and yields events as they arrive.

Cost controls (per plan):
- Per-call USD ceiling: MULTI_AGENT_USD_CEILING = 0.50
- Wall-clock budget: 60s
- Each specialist is capped at max_iterations=4 by specialists.py
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import AsyncIterator

from apps.api.config import get_settings
from apps.api.llm.cost_ledger import add_spend
from apps.api.llm.router import route
from apps.api.llm.schemas import RouterDecision, SpecialistResult
from apps.api.llm.specialists import run_planner, run_specialist

MULTI_AGENT_USD_CEILING = 0.50
MULTI_AGENT_WALL_CLOCK_S = 60.0


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


async def run_multi_agent(dataset_id: str, user_question: str) -> AsyncIterator[str]:
    """Yield SSE events for a multi-agent run.

    Event order:
    1. `router_decision` — what the Router picked, with rationale
    2. `agent_start` (planner) — Planner is starting
    3. `agent_dispatch` (planner → specialist) — each time the Planner dispatches
       `agent_start` (specialist) — specialist begins
       `tool_call_start` + `tool_call_result` per tool the specialist runs
       `agent_complete` (specialist) — specialist done, with summary + usage
    4. `agent_complete` (planner) — Planner done
    5. `final` — overall text, accumulated tool_calls, total usage
    Each event also carries `agent` so the frontend can group them in the agent lane.
    """
    started = time.monotonic()
    settings = get_settings()

    # Step 1: Router. Fast (~300ms), synchronous — fine to block before streaming starts.
    decision = route(user_question)
    yield _sse({
        "type": "router_decision",
        "path": decision.path,
        "specialist": decision.specialist,
        "rationale": decision.rationale,
    })

    if decision.path == "single":
        # Defer to the existing single-agent SSE generator.
        from apps.api.llm.loop import stream_chat_sse
        async for event in stream_chat_sse(dataset_id, [{"role": "user", "content": user_question}]):
            yield event
        return

    # Multi-agent path. Run Planner in a thread; bridge via asyncio.Queue.
    queue: asyncio.Queue[dict] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    accumulated_specialist_results: list[SpecialistResult] = []
    total_usd_spent_holder = {"value": 0.0}
    error_holder: dict = {}

    def _put_threadsafe(event: dict) -> None:
        # Called from worker thread; schedules a put_nowait on the event loop.
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def _dispatcher(specialist: str, sub_question: str, context: str | None) -> SpecialistResult:
        # Check budget ceiling before each dispatch.
        if total_usd_spent_holder["value"] >= MULTI_AGENT_USD_CEILING:
            _put_threadsafe({
                "type": "cost_cap_hit",
                "agent": specialist,
                "spent_usd": round(total_usd_spent_holder["value"], 4),
                "cap_usd": MULTI_AGENT_USD_CEILING,
            })
            # Return a synthetic "no work done" result so the Planner sees the cap.
            from apps.api.llm.schemas import ChatUsage
            return SpecialistResult(
                specialist=specialist,  # type: ignore[arg-type]
                summary=f"Skipped — multi-agent USD ceiling (${MULTI_AGENT_USD_CEILING}) reached.",
                key_findings=[],
                tool_calls=[],
                usage=ChatUsage(),
                stop_reason="cost_cap",
                iterations=0,
            )
        # Wall-clock guard.
        if time.monotonic() - started > MULTI_AGENT_WALL_CLOCK_S:
            from apps.api.llm.schemas import ChatUsage
            return SpecialistResult(
                specialist=specialist,  # type: ignore[arg-type]
                summary="Skipped — multi-agent wall-clock budget reached.",
                key_findings=[],
                tool_calls=[],
                usage=ChatUsage(),
                stop_reason="wall_clock",
                iterations=0,
            )

        _put_threadsafe({
            "type": "agent_dispatch",
            "agent": "planner",
            "from": "planner",
            "to": specialist,
            "sub_question": sub_question,
        })
        _put_threadsafe({
            "type": "agent_start",
            "agent": specialist,
            "task": sub_question,
        })
        try:
            result = run_specialist(specialist, dataset_id, sub_question, context)  # type: ignore[arg-type]
        except Exception as e:
            _put_threadsafe({
                "type": "error",
                "agent": specialist,
                "message": f"{type(e).__name__}: {e}",
            })
            raise

        total_usd_spent_holder["value"] += result.usage.estimated_usd
        accumulated_specialist_results.append(result)
        _put_threadsafe({
            "type": "agent_complete",
            "agent": specialist,
            "summary": result.summary,
            "usage": result.usage.model_dump(),
            "n_tool_calls": len(result.tool_calls),
        })
        return result

    def _worker():
        try:
            yield_event = lambda e: _put_threadsafe(e)
            yield_event({"type": "agent_start", "agent": "planner", "task": user_question})
            planner_result = run_planner(dataset_id, user_question, dispatcher=_dispatcher)
            total_usd_spent_holder["value"] += planner_result.usage.estimated_usd
            yield_event({
                "type": "agent_complete",
                "agent": "planner",
                "summary": planner_result.summary,
                "usage": planner_result.usage.model_dump(),
                "n_tool_calls": len(planner_result.tool_calls),
            })
            yield_event({
                "type": "final",
                "text": planner_result.summary,
                "tool_calls": [tc.model_dump() for tc in planner_result.tool_calls],
                "specialist_count": len(accumulated_specialist_results),
                "total_usd": round(total_usd_spent_holder["value"], 4),
                "iterations": planner_result.iterations,
                "stop_reason": planner_result.stop_reason,
                "agent": "planner",
            })
        except Exception as e:
            error_holder["error"] = f"{type(e).__name__}: {e}"
            _put_threadsafe({"type": "error", "message": error_holder["error"]})
        finally:
            _put_threadsafe({"type": "_done"})

    thread = threading.Thread(target=_worker, name="multi-agent-planner", daemon=True)
    thread.start()

    # Drain the queue until the worker signals done.
    while True:
        event = await queue.get()
        if event.get("type") == "_done":
            break
        yield _sse(event)

    # Persist the total spend to the daily ledger.
    if total_usd_spent_holder["value"] > 0:
        add_spend(settings.data_path, total_usd_spent_holder["value"], context="multi_agent")
