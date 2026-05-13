"""Tool-use loop with Anthropic Claude.

Hard caps (per CLAUDE.md):
- max 8 tool-call iterations per user turn
- max_tokens = 1024 on final response
- 30s wall-clock budget per turn

Caching strategy:
- System prompt (cached, breakpoint set)
- Tool definitions (cached, breakpoint set)
- Dataset summary as the *first* user message in the conversation (cached, breakpoint set)
- Subsequent turns are not cached (small)

We expose two entrypoints:
- `run_chat_blocking(...)` returns a single ChatResponse (used by the eval harness + tests).
- `stream_chat_sse(...)` async-generates SSE events (used by the route).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

import anthropic
from anthropic.types import MessageParam

from apps.api.config import get_settings
from apps.api.llm.cost_ledger import add_spend, check_budget
from apps.api.llm.executors import ToolExecutionError, execute_tool
from apps.api.llm.prompts import SYSTEM_PROMPT, build_dataset_summary
from apps.api.llm.schemas import ChatResponse, ChatUsage, ToolCallRecord
from apps.api.llm.tools import ALL_TOOL_DEFINITIONS, TOOL_DEFINITIONS

MAX_ITERATIONS = 8
MAX_OUTPUT_TOKENS = 2048  # extended thinking budget eats into max_tokens; bump headroom
WALL_CLOCK_BUDGET_S = 30.0
EXTENDED_THINKING_BUDGET_TOKENS = 1024

# Sonnet 4.6 pricing (USD per million tokens) per Anthropic console as of 2026-05.
INPUT_PRICE_PER_M = 3.0
OUTPUT_PRICE_PER_M = 15.0
CACHE_WRITE_PRICE_PER_M = 3.75   # 25% premium on input
CACHE_READ_PRICE_PER_M = 0.30    # 10% of input


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def _async_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)


def _system_blocks(custom: str | None = None) -> list[dict]:
    return [
        {"type": "text", "text": custom or SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
    ]


def _filter_tools(subset: list[str] | None) -> list[dict]:
    if subset is None:
        return list(TOOL_DEFINITIONS)
    keep = set(subset)
    # Search the broader registry (chat + planner tools) so the Planner can request
    # `dispatch_specialist` / `submit_final_answer` via tool_subset.
    return [t for t in ALL_TOOL_DEFINITIONS if t["name"] in keep]


def _cached_tools(subset: list[str] | None = None) -> list[dict]:
    """Mark the last tool def with cache_control to break the prefix at end of tools."""
    tools = _filter_tools(subset)
    out = []
    for i, t in enumerate(tools):
        copy = dict(t)
        if i == len(tools) - 1:
            copy["cache_control"] = {"type": "ephemeral"}
        out.append(copy)
    return out


def _build_messages(
    dataset_id: str,
    user_turns: list[dict],
    *,
    include_dataset_summary: bool = True,
) -> list[MessageParam]:
    """Prepend the dataset summary as a user message with cache_control on the last block."""
    messages: list[MessageParam] = []
    if not user_turns:
        return messages
    first = user_turns[0]
    rest = user_turns[1:]
    if include_dataset_summary:
        summary = build_dataset_summary(dataset_id)
        first_content = [
            {"type": "text", "text": summary, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": first["content"]},
        ]
        messages.append({"role": "user", "content": first_content})
    else:
        messages.append({"role": "user", "content": first["content"]})
    for m in rest:
        messages.append({"role": m["role"], "content": m["content"]})
    return messages


def _accumulate_usage(usage: ChatUsage, response_usage) -> ChatUsage:
    in_tokens = getattr(response_usage, "input_tokens", 0) or 0
    out_tokens = getattr(response_usage, "output_tokens", 0) or 0
    cache_create = getattr(response_usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(response_usage, "cache_read_input_tokens", 0) or 0
    usage.input_tokens += in_tokens
    usage.output_tokens += out_tokens
    usage.cache_creation_input_tokens += cache_create
    usage.cache_read_input_tokens += cache_read
    usage.estimated_usd += (
        in_tokens * INPUT_PRICE_PER_M / 1e6
        + out_tokens * OUTPUT_PRICE_PER_M / 1e6
        + cache_create * CACHE_WRITE_PRICE_PER_M / 1e6
        + cache_read * CACHE_READ_PRICE_PER_M / 1e6
    )
    return usage


def run_chat_blocking(
    dataset_id: str,
    user_turns: list[dict],
    model: str | None = None,
    *,
    system_prompt: str | None = None,
    tool_subset: list[str] | None = None,
    max_iterations: int = MAX_ITERATIONS,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    tool_choice: dict | None = None,
    include_dataset_summary: bool = True,
    enable_thinking: bool = True,
) -> ChatResponse:
    """Single-shot tool-use loop. Used by chat tests, eval harness, and the
    anomaly + auto-plan agents.

    Optional keyword args let callers narrow the prompt and tool surface for
    focused agent workflows without forking the loop.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    check_budget(settings.data_path, settings.llm_daily_usd_budget)
    client = _client()
    model = model or settings.anthropic_model

    messages = _build_messages(dataset_id, user_turns, include_dataset_summary=include_dataset_summary)
    tool_calls: list[ToolCallRecord] = []
    usage = ChatUsage()
    started = time.monotonic()
    text_out = ""
    stop_reason = "max_iterations"
    iteration = 0

    for iteration in range(max_iterations):
        if time.monotonic() - started > WALL_CLOCK_BUDGET_S:
            stop_reason = "wall_clock_budget"
            break
        kwargs: dict = dict(
            model=model,
            max_tokens=max_output_tokens,
            system=_system_blocks(system_prompt),
            tools=_cached_tools(tool_subset),
            messages=messages,
        )
        if enable_thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": EXTENDED_THINKING_BUDGET_TOKENS}
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        response = client.messages.create(**kwargs)
        usage = _accumulate_usage(usage, response.usage)
        stop_reason = response.stop_reason or "unknown"

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]
        if text_blocks:
            text_out = "\n".join(b.text for b in text_blocks).strip()

        if not tool_uses:
            break

        # Append assistant turn (the request to use tools)
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool call and append a single tool_result user turn
        tool_results = []
        for tu in tool_uses:
            t0 = time.monotonic()
            err: str | None = None
            try:
                result = execute_tool(tu.name, dataset_id, dict(tu.input))
            except ToolExecutionError as e:
                err = str(e)
                result = {"error": err}
            duration_ms = int((time.monotonic() - t0) * 1000)
            tool_calls.append(ToolCallRecord(
                name=tu.name, arguments=dict(tu.input),
                result=result, duration_ms=duration_ms, error=err,
            ))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
                "is_error": err is not None,
            })
        messages.append({"role": "user", "content": tool_results})

    if usage.estimated_usd > 0:
        add_spend(settings.data_path, usage.estimated_usd, context="chat_blocking")
    return ChatResponse(
        text=text_out,
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=stop_reason,
        iterations=iteration + 1,
    )


async def stream_chat_sse(
    dataset_id: str,
    user_turns: list[dict],
    model: str | None = None,
) -> AsyncIterator[str]:
    """Yield Server-Sent Events for streaming UI.

    Event types:
    - {"type":"plan", "text": "..."}                — only emitted if the assistant outputs a plan-only turn
    - {"type":"tool_call_start", "name":...}
    - {"type":"tool_call_result", "name":..., "result": {...}, "duration_ms": ...}
    - {"type":"text_delta", "text":"..."}            — partial assistant text
    - {"type":"final", "text":..., "tool_calls": [...], "usage": {...}, "stop_reason":..., "iterations":...}
    - {"type":"error", "message":"..."}
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        yield _sse({"type": "error", "message": "ANTHROPIC_API_KEY is not set"})
        return
    try:
        check_budget(settings.data_path, settings.llm_daily_usd_budget)
    except Exception as e:
        from apps.api.llm.cost_ledger import BudgetExceededError
        if isinstance(e, BudgetExceededError):
            yield _sse({
                "type": "error",
                "message": str(e),
                "code": "budget_exceeded",
                "spent_usd": e.spent_usd,
                "budget_usd": e.budget_usd,
            })
            return
        raise
    client = _async_client()
    model = model or settings.anthropic_model

    messages = _build_messages(dataset_id, user_turns)
    tool_calls: list[ToolCallRecord] = []
    usage = ChatUsage()
    text_out = ""
    started = time.monotonic()
    stop_reason = "max_iterations"
    iteration = 0

    for iteration in range(MAX_ITERATIONS):
        if time.monotonic() - started > WALL_CLOCK_BUDGET_S:
            stop_reason = "wall_clock_budget"
            break

        async with client.messages.stream(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=_system_blocks(),
            tools=_cached_tools(),
            messages=messages,
            thinking={"type": "enabled", "budget_tokens": EXTENDED_THINKING_BUDGET_TOKENS},
        ) as stream:
            this_text = ""
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    this_text += event.delta.text
                    yield _sse({"type": "text_delta", "text": event.delta.text})
            response = await stream.get_final_message()

        usage = _accumulate_usage(usage, response.usage)
        stop_reason = response.stop_reason or "unknown"

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if this_text:
            text_out = this_text.strip()

        if not tool_uses:
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tu in tool_uses:
            yield _sse({"type": "tool_call_start", "name": tu.name, "arguments": dict(tu.input)})
            t0 = time.monotonic()
            err: str | None = None
            try:
                result = execute_tool(tu.name, dataset_id, dict(tu.input))
            except ToolExecutionError as e:
                err = str(e)
                result = {"error": err}
            duration_ms = int((time.monotonic() - t0) * 1000)
            tool_calls.append(ToolCallRecord(
                name=tu.name, arguments=dict(tu.input),
                result=result, duration_ms=duration_ms, error=err,
            ))
            yield _sse({
                "type": "tool_call_result",
                "name": tu.name,
                "result": result,
                "duration_ms": duration_ms,
                "error": err,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str),
                "is_error": err is not None,
            })
        messages.append({"role": "user", "content": tool_results})

    if usage.estimated_usd > 0:
        add_spend(settings.data_path, usage.estimated_usd, context="chat_sse")
    yield _sse({
        "type": "final",
        "text": text_out,
        "tool_calls": [tc.model_dump() for tc in tool_calls],
        "usage": usage.model_dump(),
        "stop_reason": stop_reason,
        "iterations": iteration + 1,
    })


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"
