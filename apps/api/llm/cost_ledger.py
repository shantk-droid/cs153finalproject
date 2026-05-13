"""Daily LLM spend ledger.

Persisted at `{data_path}/llm_insights/cost_ledger.{YYYY-MM-DD}.json` to match the existing
insights cache pattern. The `llm_daily_usd_budget` Settings field (config.py) is enforced here
— `check_budget()` raises `BudgetExceededError` at the start of every chat call, and
`add_spend()` is called after each call to accumulate spend.

The ledger is per-day; tomorrow starts a fresh file. Old files stay on disk indefinitely so a
human can audit historical spend.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional


class BudgetExceededError(RuntimeError):
    """Raised by `check_budget()` when today's spend has already met or exceeded the cap.

    Chat routes should catch this and return HTTP 429.
    """

    def __init__(self, spent_usd: float, budget_usd: float) -> None:
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd
        super().__init__(
            f"Daily LLM budget of ${budget_usd:.2f} reached — already spent ${spent_usd:.4f} today."
        )


def _ledger_path(data_path: Path, on_date: Optional[date] = None) -> Path:
    on_date = on_date or date.today()
    return Path(data_path) / "llm_insights" / f"cost_ledger.{on_date.isoformat()}.json"


def read_today_usd(data_path: Path) -> float:
    """Return total USD spent today across all chat calls. Returns 0.0 if no ledger yet."""
    path = _ledger_path(data_path)
    if not path.exists():
        return 0.0
    try:
        with path.open() as f:
            return float(json.load(f).get("total_usd", 0.0))
    except (json.JSONDecodeError, OSError, ValueError):
        return 0.0


def add_spend(data_path: Path, usd: float, context: str = "chat") -> None:
    """Append a spend record to today's ledger. Atomic-ish via simple rewrite — sufficient for v1.

    `context` is a free-form tag (e.g. "chat", "briefing", "router", "judge") so we can attribute
    spend across the multi-agent system later.
    """
    if usd <= 0:
        return
    path = _ledger_path(data_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {"date": date.today().isoformat(), "total_usd": 0.0, "entries": []}
    if path.exists():
        try:
            with path.open() as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            pass
    existing["total_usd"] = float(existing.get("total_usd", 0.0)) + float(usd)
    entries = existing.setdefault("entries", [])
    entries.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "usd": float(usd),
        "context": context,
    })
    if len(entries) > 1000:
        existing["entries"] = entries[-1000:]
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(existing, f, indent=2)
    tmp.replace(path)


def check_budget(data_path: Path, budget_usd: float) -> None:
    """Raise BudgetExceededError if today's spend has already met or exceeded the budget.

    Called at the top of every chat call. Note: this is a pre-check; it cannot prevent a single
    expensive call from going over (since cost is only known after the model responds), but it
    blocks new calls once the cap is hit.
    """
    if budget_usd <= 0:
        return
    spent = read_today_usd(data_path)
    if spent >= budget_usd:
        raise BudgetExceededError(spent_usd=spent, budget_usd=budget_usd)
