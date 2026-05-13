"""Lightweight Router — Haiku 4.5 classifier that picks between single-agent and multi-agent paths.

The Router runs *once per user turn* before any work happens. Its only output is a structured
RouterDecision (path + specialist hint + rationale). The Anthropic tool-use forced-output
pattern (`tool_choice={"type": "tool", "name": "route"}`) gives us a clean JSON shape with no
parsing risk.

Cost: ~$0.001 per call (Haiku 4.5, ≤128 output tokens). Latency: 200-400ms TTFB.

If the API key is missing or Anthropic errors, the Router silently degrades to `path: "single"`
— that's the safest default and matches the pre-multi-agent behavior.
"""

from __future__ import annotations

import anthropic

from apps.api.config import get_settings
from apps.api.llm.cost_ledger import add_spend
from apps.api.llm.prompts import ROUTER_SYSTEM
from apps.api.llm.schemas import RouterDecision

ROUTER_MODEL = "claude-haiku-4-5-20251001"
ROUTER_MAX_TOKENS = 128

# Haiku 4.5 pricing as of 2026-05.
HAIKU_INPUT_PRICE_PER_M = 0.80
HAIKU_OUTPUT_PRICE_PER_M = 4.0


_ROUTE_TOOL = {
    "name": "route",
    "description": "Emit the routing decision. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "enum": ["single", "multi"],
                "description": (
                    "Pick 'single' for any question answerable in 1-2 tool calls; "
                    "'multi' for multi-specialist decompositions."
                ),
            },
            "specialist": {
                "type": "string",
                "enum": ["forecaster", "risk", "buyer", "planner"],
                "description": "Most relevant specialist (hint).",
            },
            "rationale": {
                "type": "string",
                "description": "One short sentence explaining the choice.",
            },
        },
        "required": ["path", "rationale"],
        "additionalProperties": False,
    },
}


def route(user_question: str) -> RouterDecision:
    """Classify a user turn. Returns RouterDecision; never raises — falls back to single on error."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return RouterDecision(path="single", specialist=None, rationale="ANTHROPIC_API_KEY not set; using single-agent fallback.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=ROUTER_MAX_TOKENS,
            system=ROUTER_SYSTEM,
            tools=[_ROUTE_TOOL],
            tool_choice={"type": "tool", "name": "route"},
            messages=[{"role": "user", "content": user_question}],
        )
    except Exception as e:
        return RouterDecision(path="single", specialist=None, rationale=f"Router error ({type(e).__name__}); using single-agent fallback.")

    in_tokens = getattr(response.usage, "input_tokens", 0) or 0
    out_tokens = getattr(response.usage, "output_tokens", 0) or 0
    cost_usd = (
        in_tokens * HAIKU_INPUT_PRICE_PER_M / 1e6
        + out_tokens * HAIKU_OUTPUT_PRICE_PER_M / 1e6
    )
    if cost_usd > 0:
        add_spend(settings.data_path, cost_usd, context="router")

    tool_uses = [b for b in response.content if b.type == "tool_use" and b.name == "route"]
    if not tool_uses:
        return RouterDecision(path="single", specialist=None, rationale="Router did not emit a tool call; using single-agent fallback.")
    args = dict(tool_uses[0].input)
    try:
        return RouterDecision(
            path=args.get("path", "single"),
            specialist=args.get("specialist"),
            rationale=args.get("rationale", ""),
        )
    except Exception:
        return RouterDecision(path="single", specialist=None, rationale="Router output failed validation; using single-agent fallback.")
