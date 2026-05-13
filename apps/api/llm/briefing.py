"""Scheduled morning briefing — runs the Planner agent against every dataset, once a day.

Output is cached at `{data_path}/llm_insights/briefing.{dataset_id}.{YYYY-MM-DD}.json` using
the same on-disk pattern as the panel/supplier/sku insights cache. The dashboard reads the
cached file lazily; if today's file isn't there, the UI shows a "briefing will generate at
9am PT" placeholder.

Cron: weekday 9am Pacific (14:00 UTC summer / 15:00 UTC winter). We pick 14:00 UTC and accept
a 1-hour drift across DST — fine for an internal briefing.

Cost: each dataset = one Planner run (~$0.10 in normal use, ~$0.50 cap). With a single demo
dataset, total daily spend ~$0.10. A 10-dataset deployment ~$1/day.

Per CLAUDE.md the previous "AutoPlan / draft PO" feature was removed 2026-05-05. This briefing
is **proposal-only** — it never creates POs. The user clicks through to act on it.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from apps.api.config import get_settings
from apps.api.llm.schemas import SpecialistResult
from apps.api.llm.specialists import run_planner

BRIEFING_PROMPT = """It's the start of a new day. Generate a concise briefing for this dataset
covering today's top priorities. Cover (in order):
1. The most urgent reorder action this week (one SKU + supplier, with a one-line reason).
2. Any data-quality concern worth flagging (regime breaks, low history, calibration drift).
3. One forward-looking observation (forecast surprise, capacity risk, supplier widening).

Keep the answer to 5-7 sentences. Lead with the recommendation. Cite specific SKU IDs,
supplier names, and numbers. No preamble or headings — just the prose."""


def _briefing_path(data_path: Path, dataset_id: str, on_date: date | None = None) -> Path:
    on_date = on_date or date.today()
    return Path(data_path) / "llm_insights" / f"briefing.{dataset_id}.{on_date.isoformat()}.json"


def read_cached_briefing(dataset_id: str, on_date: date | None = None) -> dict | None:
    """Return today's cached briefing JSON, or None if not yet generated."""
    settings = get_settings()
    path = _briefing_path(settings.data_path, dataset_id, on_date)
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def generate_briefing(dataset_id: str) -> dict:
    """Run the Planner against this dataset and persist a briefing JSON.

    Used both by the Modal scheduled job (`scheduled_briefing`) and by a manual
    POST /datasets/{id}/briefing endpoint for testing without waiting for cron.

    Returns the briefing dict. Idempotent: calling twice on the same day overwrites
    the same file (kept under llm_insights/, sha256-equivalent — the date is the key).
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        # Graceful fallback: ship an empty briefing so the dashboard can still render a
        # placeholder. Matches the pattern in llm/insights.py.
        result_obj: dict = {
            "dataset_id": dataset_id,
            "date": date.today().isoformat(),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "text": "",
            "stub": True,
            "reason": "ANTHROPIC_API_KEY not set",
            "usage_usd": 0.0,
        }
        _write_briefing(dataset_id, result_obj)
        return result_obj

    # Run the Planner with a no-op dispatcher — for the briefing we want the planner to
    # actually call specialists internally, so we pass the real run_specialist as the
    # dispatcher. Each specialist call is bounded by max_iterations=4.
    from apps.api.llm.specialists import run_specialist

    def _dispatcher(specialist: str, sub_question: str, context: str | None) -> SpecialistResult:
        return run_specialist(specialist, dataset_id, sub_question, context)  # type: ignore[arg-type]

    try:
        planner_result = run_planner(dataset_id, BRIEFING_PROMPT, dispatcher=_dispatcher)
        text = planner_result.summary
        usage = planner_result.usage.estimated_usd
    except Exception as e:
        text = ""
        usage = 0.0
        error = f"{type(e).__name__}: {e}"
    else:
        error = None

    out = {
        "dataset_id": dataset_id,
        "date": date.today().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "text": text,
        "stub": not bool(text),
        "usage_usd": round(usage, 4),
    }
    if error:
        out["error"] = error
    _write_briefing(dataset_id, out)
    return out


def _write_briefing(dataset_id: str, payload: dict) -> None:
    settings = get_settings()
    path = _briefing_path(settings.data_path, dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def generate_all_briefings() -> dict:
    """Iterate every dataset on disk and refresh today's briefing. Used by the cron job.

    Returns a summary `{n_datasets, n_succeeded, n_failed, total_usd}` for the cron logs.
    Continues past per-dataset failures so a single bad dataset doesn't break the batch.
    """
    settings = get_settings()
    datasets_dir = settings.data_path
    if not datasets_dir.exists():
        return {"n_datasets": 0, "n_succeeded": 0, "n_failed": 0, "total_usd": 0.0}

    # The dataset_path() helper produces `{data_dir}/{id}.duckdb`; iterate matching files.
    dataset_ids = [p.stem for p in datasets_dir.glob("*.duckdb")]
    n_succ = 0
    n_fail = 0
    total_usd = 0.0
    for dsid in dataset_ids:
        try:
            out = generate_briefing(dsid)
            total_usd += float(out.get("usage_usd", 0.0))
            if out.get("text"):
                n_succ += 1
            else:
                n_fail += 1
        except Exception:
            n_fail += 1
    return {
        "n_datasets": len(dataset_ids),
        "n_succeeded": n_succ,
        "n_failed": n_fail,
        "total_usd": round(total_usd, 4),
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
    }
