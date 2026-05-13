"""Agent task suite eval harness — extends the single-agent eval.py with multi-agent + judge.

Each task in `evals/agent_tasks.yaml` looks like:
  - id: my-task
    question: "Plan next week's reorders with a $30k cap and flag any supplier risk."
    mode: "multi"                              # "single" | "multi" (default: "single")
    expect_tools: ["plan_reorder_week"]         # at least one (legacy matcher)
    expect_tools_all: []                        # all of these (legacy)
    expect_no_tools: []                          # none of these (legacy)
    expect_text_contains_any: []                 # at least one substring
    expect_specialists: ["buyer", "risk"]        # multi only: at least these specialists invoked
    expect_handoffs: 2                           # multi only: minimum number of agent_dispatch events
    judge_rubric:                                # free-form only: triggers judge.py
      expected_summary: "Should include..."

Run:
    PYTHONPATH=$PWD .venv/bin/python -m apps.api.llm.agent_eval --dataset-id <id>

CI gates:
    single-agent suite (mode: single) — pass rate ≥ 90% (matches existing eval.py)
    multi-agent suite  (mode: multi)  — pass rate ≥ 75% (lower headroom for judge variance)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from apps.api.llm.judge import judge
from apps.api.llm.loop import run_chat_blocking
from apps.api.llm.orchestrator import run_multi_agent


def _check_matchers(test: dict, called_tool_names: set[str], final_text: str) -> tuple[bool, list[str]]:
    failures: list[str] = []
    expect_tools_any = set(test.get("expect_tools") or [])
    expect_tools_all = set(test.get("expect_tools_all") or [])
    expect_no_tools = set(test.get("expect_no_tools") or [])
    expect_text_any = [s.lower() for s in (test.get("expect_text_contains_any") or [])]

    if expect_tools_any and not (expect_tools_any & called_tool_names):
        failures.append(f"none of expected tools {sorted(expect_tools_any)} called; got {sorted(called_tool_names)}")
    if expect_tools_all - called_tool_names:
        failures.append(f"missing required tools: {sorted(expect_tools_all - called_tool_names)}")
    forbidden = expect_no_tools & called_tool_names
    if forbidden:
        failures.append(f"forbidden tools called: {sorted(forbidden)}")
    if expect_text_any:
        text_lower = (final_text or "").lower()
        if not any(s in text_lower for s in expect_text_any):
            failures.append(f"text missing any of {expect_text_any!r}")
    return (not failures), failures


def _run_single(dataset_id: str, question: str) -> tuple[set[str], str, dict]:
    response = run_chat_blocking(
        dataset_id=dataset_id,
        user_turns=[{"role": "user", "content": question}],
    )
    return (
        {tc.name for tc in response.tool_calls},
        response.text or "",
        {
            "iterations": response.iterations,
            "stop_reason": response.stop_reason,
            "usage_usd": response.usage.estimated_usd,
            "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls],
        },
    )


def _run_multi(dataset_id: str, question: str) -> tuple[set[str], str, dict]:
    """Drain the orchestrator's SSE stream into structured fields."""
    import asyncio

    async def _drain():
        events = []
        async for raw in run_multi_agent(dataset_id, question):
            # raw is "data: {...}\n\n"
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            try:
                events.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                continue
        return events

    events = asyncio.run(_drain())
    tool_calls: list[dict] = []
    specialists_used: set[str] = set()
    handoffs = 0
    final_text = ""
    total_usd = 0.0
    for e in events:
        t = e.get("type")
        if t == "tool_call_result":
            tool_calls.append({"name": e.get("name"), "arguments": e.get("arguments") or {}})
        elif t == "agent_dispatch":
            handoffs += 1
            if e.get("to"):
                specialists_used.add(e["to"])
        elif t == "agent_complete":
            agent = e.get("agent")
            if agent and agent != "planner":
                specialists_used.add(agent)
            # Track usage
            u = e.get("usage") or {}
            total_usd += float(u.get("estimated_usd") or 0.0)
        elif t == "final":
            final_text = e.get("text") or ""
            total_usd += float(e.get("total_usd") or 0.0)
    return (
        {tc["name"] for tc in tool_calls},
        final_text,
        {
            "specialists_used": sorted(specialists_used),
            "handoffs": handoffs,
            "n_tool_calls": len(tool_calls),
            "usage_usd": total_usd,
            "tool_calls": tool_calls,
        },
    )


def run_task(dataset_id: str, test: dict, *, skip_judge: bool = False) -> dict:
    mode = (test.get("mode") or "single").lower()
    if mode not in ("single", "multi"):
        raise ValueError(f"invalid mode for task {test.get('id')!r}: {mode}")
    question = test["question"]
    started = time.monotonic()
    if mode == "single":
        called, final_text, trace = _run_single(dataset_id, question)
    else:
        called, final_text, trace = _run_multi(dataset_id, question)
    elapsed_s = time.monotonic() - started

    passed, failures = _check_matchers(test, called, final_text)

    # Multi-only structural checks
    if mode == "multi":
        expect_specialists = set(test.get("expect_specialists") or [])
        if expect_specialists:
            used = set(trace.get("specialists_used") or [])
            missing = expect_specialists - used
            if missing:
                passed = False
                failures.append(f"missing expected specialists: {sorted(missing)}")
        expect_handoffs = test.get("expect_handoffs")
        if expect_handoffs is not None and trace.get("handoffs", 0) < int(expect_handoffs):
            passed = False
            failures.append(f"too few handoffs: {trace.get('handoffs', 0)} < {expect_handoffs}")

    # Judge (free-form only)
    judge_block: dict | None = None
    rubric = test.get("judge_rubric")
    if rubric and not skip_judge:
        verdict = judge(
            question=question,
            final_text=final_text,
            tool_call_summary=trace.get("tool_calls") or [],
            expected_summary=rubric.get("expected_summary"),
        )
        if verdict is None:
            judge_block = {"skipped": True, "reason": "judge unavailable"}
        else:
            judge_block = {
                "grounding": verdict.grounding,
                "completeness": verdict.completeness,
                "conciseness": verdict.conciseness,
                "calibration": verdict.calibration,
                "total": verdict.total,
                "passed": verdict.passed,
                "rationale": verdict.rationale,
                "cost_usd": round(verdict.cost_usd, 4),
            }
            if not verdict.passed:
                passed = False
                failures.append(f"judge: total={verdict.total}/12 grounding={verdict.grounding} ({verdict.rationale})")

    return {
        "id": test.get("id", "?"),
        "mode": mode,
        "passed": passed,
        "failures": failures,
        "elapsed_s": round(elapsed_s, 2),
        "trace": trace,
        "final_text": final_text,
        "judge": judge_block,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent task suite eval.")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--questions", default="evals/agent_tasks.yaml")
    parser.add_argument("--max", type=int, default=None)
    parser.add_argument("--mode", choices=["single", "multi", "all"], default="all", help="Filter by mode.")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--threshold-single", type=float, default=0.9)
    parser.add_argument("--threshold-multi", type=float, default=0.75)
    parser.add_argument("--no-judge", action="store_true", help="Skip the free-form judge (faster, no Haiku cost).")
    args = parser.parse_args()

    path = Path(args.questions)
    if not path.exists():
        print(f"error: questions file not found: {path}", file=sys.stderr)
        return 2
    tests = yaml.safe_load(path.read_text())["questions"]
    if args.mode != "all":
        tests = [t for t in tests if (t.get("mode") or "single") == args.mode]
    if args.max:
        tests = tests[: args.max]

    results: list[dict] = []
    for test in tests:
        try:
            r = run_task(args.dataset_id, test, skip_judge=args.no_judge)
        except Exception as e:
            r = {"id": test.get("id", "?"), "mode": (test.get("mode") or "single"), "passed": False,
                 "failures": [f"exception: {type(e).__name__}: {e}"]}
        results.append(r)
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['mode']:>5}  {r['id']:<40}  {r.get('elapsed_s', '?')}s  {'; '.join(r.get('failures', [])) if not r['passed'] else ''}")

    single = [r for r in results if r["mode"] == "single"]
    multi = [r for r in results if r["mode"] == "multi"]
    pass_single = sum(1 for r in single if r["passed"]) / max(1, len(single))
    pass_multi = sum(1 for r in multi if r["passed"]) / max(1, len(multi))

    print(f"\nSingle-agent: {pass_single:.0%} pass ({sum(1 for r in single if r['passed'])}/{len(single)}; threshold {args.threshold_single:.0%})")
    print(f"Multi-agent : {pass_multi:.0%} pass ({sum(1 for r in multi if r['passed'])}/{len(multi)}; threshold {args.threshold_multi:.0%})")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "results": results,
            "pass_rate_single": pass_single,
            "pass_rate_multi": pass_multi,
        }, indent=2, default=str))

    ok = True
    if single and pass_single < args.threshold_single:
        ok = False
    if multi and pass_multi < args.threshold_multi:
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
