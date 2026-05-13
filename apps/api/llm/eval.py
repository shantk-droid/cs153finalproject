"""Chat eval harness.

Run from repo root with a confirmed dataset_id:
    python -m apps.api.llm.eval --dataset-id <id>

Optional: --questions evals/chat_questions.yaml --max <n> --json-out report.json
PR-blocking pass-rate threshold: 90%.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from apps.api.llm.loop import run_chat_blocking


def _check_question(test: dict, response) -> tuple[bool, list[str]]:
    """Match semantics:
    - expect_tools: at least one of these MUST be called (not all)
    - expect_tools_all: ALL of these must be called (strict)
    - expect_no_tools: none of these may be called
    - expect_text_contains_any: at least one substring must appear in final text
    """
    failures: list[str] = []
    expect_tools_any = set(test.get("expect_tools") or [])
    expect_tools_all = set(test.get("expect_tools_all") or [])
    expect_no_tools = set(test.get("expect_no_tools") or [])
    expect_text_any = [s.lower() for s in (test.get("expect_text_contains_any") or [])]

    called = {tc.name for tc in response.tool_calls}

    if expect_tools_any and not (expect_tools_any & called):
        failures.append(f"none of expected tools {sorted(expect_tools_any)} were called; got {sorted(called)}")
    if expect_tools_all - called:
        failures.append(f"missing required tools: {sorted(expect_tools_all - called)}")
    forbidden = expect_no_tools & called
    if forbidden:
        failures.append(f"forbidden tools called: {sorted(forbidden)}")

    if expect_text_any:
        text_lower = (response.text or "").lower()
        if not any(s in text_lower for s in expect_text_any):
            failures.append(f"text missing any of {expect_text_any!r}")

    return (not failures), failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run chat eval against a confirmed dataset.")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--questions", default="evals/chat_questions.yaml")
    parser.add_argument("--max", type=int, default=None, help="Limit how many questions run")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--threshold", type=float, default=0.9, help="Pass-rate threshold for non-zero exit")
    args = parser.parse_args()

    qpath = Path(args.questions)
    if not qpath.exists():
        print(f"questions file not found: {qpath}", file=sys.stderr)
        return 2
    spec = yaml.safe_load(qpath.read_text())
    questions = spec["questions"]
    if args.max is not None:
        questions = questions[: args.max]

    results = []
    n_pass = 0
    total_usd = 0.0
    total_secs = 0.0

    for q in questions:
        print(f"  → {q['id']}", flush=True)
        t0 = time.monotonic()
        try:
            resp = run_chat_blocking(args.dataset_id, [{"role": "user", "content": q["question"]}])
            ok, failures = _check_question(q, resp)
            if ok:
                n_pass += 1
            elapsed = time.monotonic() - t0
            total_secs += elapsed
            total_usd += resp.usage.estimated_usd
            results.append({
                "id": q["id"],
                "passed": ok,
                "failures": failures,
                "iterations": resp.iterations,
                "tools_called": [tc.name for tc in resp.tool_calls],
                "stop_reason": resp.stop_reason,
                "estimated_usd": round(resp.usage.estimated_usd, 4),
                "elapsed_s": round(elapsed, 2),
                "text": resp.text[:300],
            })
            print(f"     {'PASS' if ok else 'FAIL'}  tools={[tc.name for tc in resp.tool_calls]}  ${resp.usage.estimated_usd:.4f}  {elapsed:.1f}s")
            if not ok:
                for f in failures:
                    print(f"        - {f}")
        except Exception as e:
            results.append({"id": q["id"], "passed": False, "error": str(e)})
            print(f"     ERROR: {e}")

    pass_rate = n_pass / max(1, len(questions))
    print()
    print(f"Pass rate: {n_pass}/{len(questions)} ({pass_rate:.0%})")
    print(f"Total cost: ${total_usd:.4f}, total time: {total_secs:.1f}s")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "dataset_id": args.dataset_id,
            "n_questions": len(questions),
            "n_pass": n_pass,
            "pass_rate": pass_rate,
            "total_usd": total_usd,
            "total_secs": total_secs,
            "results": results,
        }, indent=2, default=str))

    return 0 if pass_rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
