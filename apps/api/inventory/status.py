"""Per-SKU urgency status — order_now / at_risk / watch / healthy.

A lightweight heuristic that runs on the SKU list endpoint without invoking the
full recommend pipeline (which forecasts every SKU). Compares days-of-cover
against the SKU's lead time:

    order_now: on_hand <= 0 OR days_of_cover < lead_time_days
    at_risk:   days_of_cover < 1.5 × lead_time_days
    watch:     days_of_cover < 2.0 × lead_time_days
    healthy:   otherwise

If `days_of_cover` is unknown (e.g. zero recent demand), we fall back to `watch`
unless `on_hand` is zero — the user should see *something* on a stale SKU.
"""

from __future__ import annotations

from typing import Literal

SkuStatus = Literal["order_now", "at_risk", "watch", "healthy"]

DEFAULT_LEAD_TIME_DAYS = 14.0


def derive_status(
    on_hand: float | None,
    days_of_cover: float | None,
    lead_time_days: float | None,
) -> SkuStatus:
    """Triage signal for the SKU list."""
    lt = lead_time_days if (lead_time_days is not None and lead_time_days > 0) else DEFAULT_LEAD_TIME_DAYS

    if on_hand is None or on_hand <= 0:
        return "order_now"

    if days_of_cover is None:
        return "watch"

    if days_of_cover < lt:
        return "order_now"
    if days_of_cover < 1.5 * lt:
        return "at_risk"
    if days_of_cover < 2.0 * lt:
        return "watch"
    return "healthy"
