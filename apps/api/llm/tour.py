"""LLM-narrated dashboard tour — 4 steps tailored to the dataset.

Generated once per dataset (cached for 30 days). The frontend shows the tour as a
first-visit modal; subsequent visits skip it unless the user manually opens it.

When the API key is missing or the LLM errors, we fall back to a canned heuristic tour
so the UX never breaks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

from apps.api.config import get_settings
from apps.api.llm.cost_ledger import add_spend
from apps.api.llm.prompts import build_dataset_summary
from apps.api.llm.router import HAIKU_INPUT_PRICE_PER_M, HAIKU_OUTPUT_PRICE_PER_M

TOUR_MODEL = "claude-haiku-4-5-20251001"
TOUR_MAX_TOKENS = 800
TOUR_TTL_DAYS = 30

TOUR_SYSTEM = """You are writing a 4-step welcome tour for a new user of an inventory
optimizer. The dataset has just been confirmed and the user is about to see the dashboard
for the first time.

You'll receive a JSON object with summary stats: dataset_id, n_skus, n_rows, frequency,
top categories, top suppliers. Optionally also a profile_id (retail_m5, pharma_medical, etc.)
that tells you what kind of inventory this is.

Write EXACTLY 4 steps. Each step:
- title: 4-7 words, action-oriented (e.g., "Start with the action queue")
- body: 1-2 sentences. Reference one specific number from the summary when possible.
- route: one of `/dashboard/{id}`, `/dashboard/{id}/forecasts`, `/dashboard/{id}/reorder`,
  `/dashboard/{id}/frontier`, `/dashboard/{id}/quality`, `/dashboard/{id}/stress`,
  `/dashboard/{id}/settings`. The frontend will substitute {id}.

Order matters. Lead with the most useful page given the data profile (e.g., perishable
profile → newsvendor calculator first; lumpy demand → stress test).

Output a JSON array of 4 step objects, no preamble, no markdown."""


@dataclass
class TourStep:
    title: str
    body: str
    route: str


def _tour_path(dataset_id: str) -> Path:
    settings = get_settings()
    return Path(settings.data_path) / "llm_insights" / f"tour.{dataset_id}.json"


def _heuristic_tour(dataset_id: str) -> list[TourStep]:
    """Generic 4-step tour used as fallback when the LLM is unavailable.

    Keeps the route names consistent with the LLM-generated path so the frontend can render
    either source uniformly."""
    return [
        TourStep(
            title="Start with the action queue",
            body="The action queue ranks SKUs by stockout risk × revenue at risk. Triage from the top down.",
            route="/dashboard/{id}",
        ),
        TourStep(
            title="Forecast the top revenue SKUs",
            body="Each forecast comes with backtest accuracy and a 95% prediction interval — caveats included.",
            route="/dashboard/{id}/forecasts",
        ),
        TourStep(
            title="Plan this week's reorders",
            body="The reorder queue surfaces what to buy and why. Toggle budget caps in the UI.",
            route="/dashboard/{id}/reorder",
        ),
        TourStep(
            title="Check data quality",
            body="The composite score and profile comparison flag any concerns before they affect decisions.",
            route="/dashboard/{id}/quality",
        ),
    ]


def read_cached_tour(dataset_id: str) -> dict | None:
    """Return the cached tour JSON if present AND younger than TOUR_TTL_DAYS."""
    path = _tour_path(dataset_id)
    if not path.exists():
        return None
    try:
        with path.open() as f:
            cached = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    # TTL check
    gen_iso = cached.get("generated_at_utc")
    if gen_iso:
        try:
            gen_dt = datetime.fromisoformat(gen_iso.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - gen_dt > timedelta(days=TOUR_TTL_DAYS):
                return None
        except ValueError:
            pass
    return cached


def _write_tour(dataset_id: str, payload: dict) -> None:
    path = _tour_path(dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def _summary_for_tour(dataset_id: str) -> dict:
    summary_text = build_dataset_summary(dataset_id)
    return {
        "dataset_id": dataset_id,
        "summary_text": summary_text,
    }


def get_or_generate_tour(dataset_id: str) -> dict:
    """Return the cached tour, or generate + cache + return a fresh one.

    Always returns a 4-step tour — falls back to heuristic on any error so the modal can
    render uniformly. The frontend doesn't need to handle a missing-tour case.
    """
    cached = read_cached_tour(dataset_id)
    if cached is not None:
        return cached

    settings = get_settings()
    if not settings.anthropic_api_key:
        return _emit_heuristic(dataset_id, reason="ANTHROPIC_API_KEY not set")

    payload = _summary_for_tour(dataset_id)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model=TOUR_MODEL,
            max_tokens=TOUR_MAX_TOKENS,
            system=TOUR_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
    except Exception as e:
        return _emit_heuristic(dataset_id, reason=f"LLM error: {type(e).__name__}")

    in_tokens = getattr(response.usage, "input_tokens", 0) or 0
    out_tokens = getattr(response.usage, "output_tokens", 0) or 0
    cost = in_tokens * HAIKU_INPUT_PRICE_PER_M / 1e6 + out_tokens * HAIKU_OUTPUT_PRICE_PER_M / 1e6
    if cost > 0:
        add_spend(settings.data_path, cost, context="tour")

    # Parse the response — expect a JSON array of 4 step objects.
    text_blocks = [b.text for b in response.content if b.type == "text"]
    raw = "".join(text_blocks).strip()
    # Strip markdown code fences if the model wrapped the JSON
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(line for line in lines if not line.startswith("```"))

    try:
        steps = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return _emit_heuristic(dataset_id, reason="LLM output failed to parse")

    if not isinstance(steps, list) or len(steps) != 4:
        return _emit_heuristic(dataset_id, reason="LLM output wrong shape")

    cleaned = []
    for step in steps:
        if not isinstance(step, dict):
            return _emit_heuristic(dataset_id, reason="LLM output wrong step shape")
        title = str(step.get("title") or "").strip()
        body = str(step.get("body") or "").strip()
        route = str(step.get("route") or "").strip()
        if not title or not body or not route:
            return _emit_heuristic(dataset_id, reason="LLM output missing fields")
        cleaned.append({"title": title, "body": body, "route": route})

    out = {
        "dataset_id": dataset_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "llm",
        "steps": cleaned,
        "usage_usd": round(cost, 4),
    }
    _write_tour(dataset_id, out)
    return out


def _emit_heuristic(dataset_id: str, reason: str) -> dict:
    steps = _heuristic_tour(dataset_id)
    out = {
        "dataset_id": dataset_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "heuristic",
        "reason": reason,
        "steps": [{"title": s.title, "body": s.body, "route": s.route} for s in steps],
        "usage_usd": 0.0,
    }
    _write_tour(dataset_id, out)
    return out
