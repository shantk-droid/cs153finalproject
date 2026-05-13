"""LLM-as-judge for free-form agent task evaluations.

Each judge call runs Haiku 4.5 once with a four-criterion rubric (grounding, completeness,
conciseness, calibration) and a forced-tool JSON output. Used by agent_eval.py when a task
includes `judge_rubric:` (free-form tasks where exact-tool-call matchers can't apply).

Cost: ~$0.0015 per judge call. Latency: ~400ms.

The rubric is anchored in the system prompt to keep judgments stable across runs. Total score
is the sum of the four 0-3 scores. Pass = total ≥ 9/12 AND grounding ≥ 2 (i.e. the answer
can't be ungrounded even if it's well-written elsewhere).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic

from apps.api.config import get_settings
from apps.api.llm.cost_ledger import add_spend
from apps.api.llm.router import HAIKU_INPUT_PRICE_PER_M, HAIKU_OUTPUT_PRICE_PER_M

JUDGE_MODEL = "claude-haiku-4-5-20251001"
JUDGE_MAX_TOKENS = 512

JUDGE_SYSTEM = """You are an expert evaluator of an inventory-analyst AI agent's output.

For each task, you are shown: the user's question, the agent's tool-call trace (names + args),
the agent's final answer, and an `expected_summary` written by the evaluator describing what
a good answer should cover.

Score the answer on four criteria, each 0-3:

**grounding** (most important): does every number, SKU ID, and supplier name in the answer
trace back to a tool result in the trace? 0 = fabricated content; 1 = some numbers unverifiable
but mostly grounded; 2 = small numerical errors or trivial paraphrase; 3 = perfect attribution.

**completeness**: does the answer address every sub-question / dimension of the user's ask?
0 = misses most of the ask; 1 = covers half; 2 = covers most; 3 = complete.

**conciseness**: is the answer the right length? Shallow tasks ≤ 6 sentences, deep ≤ 12.
0 = much too long or much too short; 1 = noticeably off; 2 = roughly right; 3 = tight and
on-topic, no preamble or restating of the question.

**calibration**: does the answer surface caveats where warranted (low history, regime break,
wide PI, intermittent demand)? 0 = false confidence on shaky data; 1 = missing one important
caveat; 2 = adequate caveats; 3 = caveats integrated naturally without burying the answer.

Pass criteria: total ≥ 9/12 AND grounding ≥ 2.

Call the `score` tool exactly once with your verdict. Provide a one-sentence `rationale`."""


_JUDGE_TOOL = {
    "name": "score",
    "description": "Emit the judgment. Call exactly once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "grounding": {"type": "integer", "minimum": 0, "maximum": 3},
            "completeness": {"type": "integer", "minimum": 0, "maximum": 3},
            "conciseness": {"type": "integer", "minimum": 0, "maximum": 3},
            "calibration": {"type": "integer", "minimum": 0, "maximum": 3},
            "passed": {"type": "boolean"},
            "rationale": {"type": "string"},
        },
        "required": ["grounding", "completeness", "conciseness", "calibration", "passed", "rationale"],
        "additionalProperties": False,
    },
}


@dataclass
class JudgeVerdict:
    grounding: int
    completeness: int
    conciseness: int
    calibration: int
    total: int
    passed: bool
    rationale: str
    cost_usd: float


def judge(
    question: str,
    final_text: str,
    tool_call_summary: list[dict],
    expected_summary: str | None = None,
) -> JudgeVerdict | None:
    """Run the judge on one agent output. Returns None when the API key is missing or the
    Anthropic call errors — callers should fall back to a "skipped: judge unavailable" status.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None

    trace_str = "\n".join(
        f"- {tc.get('name')}({_compact_args(tc.get('arguments') or {})})"
        for tc in tool_call_summary[:20]
    ) or "  (no tools called)"

    user_payload = (
        f"USER QUESTION:\n{question}\n\n"
        f"EXPECTED SUMMARY (evaluator's notes):\n{expected_summary or '(none provided)'}\n\n"
        f"AGENT TOOL TRACE:\n{trace_str}\n\n"
        f"AGENT FINAL ANSWER:\n{final_text or '(empty)'}"
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=JUDGE_MAX_TOKENS,
            system=JUDGE_SYSTEM,
            tools=[_JUDGE_TOOL],
            tool_choice={"type": "tool", "name": "score"},
            messages=[{"role": "user", "content": user_payload}],
        )
    except Exception:
        return None

    in_tokens = getattr(response.usage, "input_tokens", 0) or 0
    out_tokens = getattr(response.usage, "output_tokens", 0) or 0
    cost = (
        in_tokens * HAIKU_INPUT_PRICE_PER_M / 1e6
        + out_tokens * HAIKU_OUTPUT_PRICE_PER_M / 1e6
    )
    if cost > 0:
        add_spend(settings.data_path, cost, context="judge")

    tool_uses = [b for b in response.content if b.type == "tool_use" and b.name == "score"]
    if not tool_uses:
        return None
    args = dict(tool_uses[0].input)
    g = int(args.get("grounding", 0))
    c = int(args.get("completeness", 0))
    cn = int(args.get("conciseness", 0))
    cl = int(args.get("calibration", 0))
    total = g + c + cn + cl
    passed_explicit = bool(args.get("passed", False))
    # Belt-and-suspenders: enforce the rubric server-side too. If the model marked passed=true
    # but failed our hard floor (grounding < 2 or total < 9), we override to False — this
    # protects against judge drift where the LLM is too generous.
    passed = passed_explicit and total >= 9 and g >= 2
    return JudgeVerdict(
        grounding=g,
        completeness=c,
        conciseness=cn,
        calibration=cl,
        total=total,
        passed=passed,
        rationale=str(args.get("rationale", "")),
        cost_usd=cost,
    )


def _compact_args(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    out = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 60:
            v = v[:60] + "…"
        out.append(f"{k}={v}")
        if len(out) >= 4:
            break
    return ", ".join(out)
