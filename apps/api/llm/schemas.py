from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    dataset_id: str
    messages: list[ChatMessage]


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict
    result: Any
    duration_ms: int
    error: str | None = None


class ChatUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    estimated_usd: float = 0.0


class ChatResponse(BaseModel):
    """Used by the non-streaming eval harness; the SSE route emits the same fields incrementally."""
    text: str
    tool_calls: list[ToolCallRecord]
    usage: ChatUsage
    stop_reason: str
    iterations: int


# ---------- Multi-agent system ----------

SpecialistName = Literal["forecaster", "risk", "buyer", "planner"]
RoutingPath = Literal["single", "multi"]


class RouterDecision(BaseModel):
    """Output of the lightweight Router classifier (Haiku 4.5).

    The Router decides whether a turn is best answered by the existing single-agent loop or
    by handing off to the multi-agent Planner. `specialist` is a hint about which specialist
    a single-agent path should *behave like* (only meaningful when path = "single" but the
    question is clearly forecasting / risk / buying flavored); the orchestrator may ignore it.
    """
    path: RoutingPath
    specialist: SpecialistName | None = None
    rationale: str


class SpecialistResult(BaseModel):
    """Structured handoff from a specialist back to the Planner.

    Specialists never talk to each other directly — the Planner is the only authority that
    sequences calls and stitches answers together. `summary` is the 2-3 sentence digest the
    Planner threads into the next specialist's prompt; `key_findings` are bullet-style facts;
    `tool_calls` is the full trace for SSE replay / debugging; `usage` accumulates spend so
    the per-call ceiling can be enforced.
    """
    specialist: SpecialistName
    summary: str
    key_findings: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    usage: ChatUsage = ChatUsage()
    stop_reason: str = "unknown"
    iterations: int = 0


class AgentEvent(BaseModel):
    """Type-safe wrapper for the new SSE events. The existing event types (text_delta,
    tool_call_*, final, error) keep their dict shape; these are additive."""
    type: Literal["agent_start", "agent_complete", "agent_dispatch", "cost_cap_hit"]
    agent: SpecialistName | None = None
    summary: str | None = None
    task: str | None = None
    sub_question: str | None = None
    from_: SpecialistName | None = None
    to: SpecialistName | None = None
    usage: ChatUsage | None = None
    spent_usd: float | None = None
    cap_usd: float | None = None
