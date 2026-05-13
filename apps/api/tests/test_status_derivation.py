"""Tests for the lightweight per-SKU status heuristic on the forecasts list."""

from __future__ import annotations

from apps.api.inventory.status import derive_status


def test_zero_or_missing_on_hand_is_order_now():
    assert derive_status(on_hand=0, days_of_cover=99, lead_time_days=7) == "order_now"
    assert derive_status(on_hand=None, days_of_cover=99, lead_time_days=7) == "order_now"


def test_cover_below_lead_time_is_order_now():
    # 5d cover, 7d lead time → order now
    assert derive_status(on_hand=10, days_of_cover=5, lead_time_days=7) == "order_now"


def test_cover_below_1p5_lead_time_is_at_risk():
    # 8d cover, 7d lead time → 1.0 < 8/7 < 1.5 → at_risk
    assert derive_status(on_hand=10, days_of_cover=8, lead_time_days=7) == "at_risk"


def test_cover_below_2x_lead_time_is_watch():
    # 12d cover, 7d lead time → 1.5 < 12/7 < 2.0 → watch
    assert derive_status(on_hand=10, days_of_cover=12, lead_time_days=7) == "watch"


def test_healthy_when_well_covered():
    assert derive_status(on_hand=100, days_of_cover=30, lead_time_days=7) == "healthy"


def test_missing_lead_time_uses_default_14d():
    # Default lead time is 14 days; cover=10 → 10 < 14 → order_now
    assert derive_status(on_hand=5, days_of_cover=10, lead_time_days=None) == "order_now"
    # Cover=20 → 14 < 20 < 21 → at_risk
    assert derive_status(on_hand=5, days_of_cover=20, lead_time_days=None) == "at_risk"


def test_missing_days_of_cover_with_stock_is_watch():
    """If on_hand > 0 but no recent demand, we don't know the cover. Watch (not healthy)."""
    assert derive_status(on_hand=10, days_of_cover=None, lead_time_days=7) == "watch"
