"""LLM-explained data-quality issues.

For the top N flagged assertions on a dataset, generate a one-paragraph plain-English
explanation citing the offending rows. Single batched Anthropic call, response cached
on disk per dataset so repeated dashboard visits don't re-pay.

Hard cost cap: 10 issues × ~200 output tokens ≈ 2K output tokens ≈ $0.04 per upload.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anthropic

from apps.api.assertions.schemas import Assertion, DataQualityReport
from apps.api.config import get_settings

EXPLAIN_SYSTEM = """You are a data-quality reviewer. The user uploaded an inventory panel and we flagged
these issues automatically. For each issue, write ONE concise paragraph (2-4 sentences):
1. State plainly what's wrong, in non-technical language.
2. Cite 1-2 of the offending row examples.
3. Suggest the most likely cause (e.g., unit error, returns column missing, stale snapshot).
4. Recommend the action: ignore, override, fix in source, or re-upload.

Output strictly as a JSON array, one object per issue, in the order given:
[
  {"code": "...", "explanation": "..."},
  ...
]
No surrounding prose."""


def _cache_key(report: DataQualityReport, max_issues: int) -> str:
    payload = {
        "dataset_id": report.dataset_id,
        "n_issues": len(report.assertions),
        "max_issues": max_issues,
        "codes": [a.code for a in report.assertions[:max_issues]],
    }
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return h[:16]


def _cache_path(dataset_id: str, key: str) -> Path:
    base = get_settings().data_path / "explanations"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{dataset_id}.{key}.json"


def explain_top_issues(
    report: DataQualityReport,
    max_issues: int = 10,
    use_cache: bool = True,
) -> dict[str, str]:
    """Return {code: explanation} for the top `max_issues` assertions in the report.

    If `ANTHROPIC_API_KEY` is not set, returns the raw assertion messages so the UI still
    has something to show. Cache hit costs $0.
    """
    settings = get_settings()
    issues = report.assertions[:max_issues]
    if not issues:
        return {}

    if use_cache:
        key = _cache_key(report, max_issues)
        cache_path = _cache_path(report.dataset_id, key)
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())
            except Exception:
                pass

    if not settings.anthropic_api_key:
        return {a.code: a.message for a in issues}

    user_payload = {
        "issues": [{
            "code": a.code,
            "severity": a.severity.value,
            "field": a.field,
            "message": a.message,
            "offending_row_count": a.offending_row_count,
            "skus_affected": a.skus_affected,
            "examples": a.offending_examples[:3],
        } for a in issues],
    }

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=EXPLAIN_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(user_payload)}],
    )

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {a.code: a.message for a in issues}

    explanations: dict[str, str] = {}
    for item in parsed:
        if isinstance(item, dict) and "code" in item and "explanation" in item:
            explanations[str(item["code"])] = str(item["explanation"])

    if use_cache:
        try:
            cache_path.write_text(json.dumps(explanations, indent=2))
        except Exception:
            pass

    return explanations
