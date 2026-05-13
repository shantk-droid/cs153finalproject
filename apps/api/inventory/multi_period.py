"""Multi-period rolling order schedule.

Given a forecast (point + quantiles per period) plus a policy + lead-time distribution,
simulate forward and emit a list of order placements with their expected arrivals.

Output is what users actually want — not "order now" but "here's the next 90 days of orders":

    [
      {date: 2025-01-15, action: "order", qty: 120, expected_arrival: 2025-01-29,
       expected_on_hand_at_arrival: 22, reason: "on_hand 65 < R=80"},
      ...
    ]

Two simulation modes:
- (Q,R) continuous review: place an order of size Q whenever projected on-hand drops to R.
- (s,S) periodic review: at every review_period, if on-hand <= s, order S - on-hand.

Both modes apply pipeline orders that arrive lead_time periods later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date, timedelta
from typing import Literal

import numpy as np
import pandas as pd

PolicyMode = Literal["QR", "sS", "base_stock"]


@dataclass
class ScheduleEntry:
    period_idx: int
    date: str
    action: Literal["order", "no_op", "delivery", "stockout"]
    qty: float = 0.0
    expected_on_hand_after_demand: float = 0.0
    expected_on_hand_after_delivery: float = 0.0
    expected_arrival: str | None = None
    reason: str | None = None


@dataclass
class Schedule:
    sku_id: str
    horizon_periods: int
    frequency: Literal["D", "W", "M"]
    starting_on_hand: float
    entries: list[ScheduleEntry]
    n_orders: int
    total_units_ordered: float
    expected_stockout_periods: int

    @property
    def actionable_orders(self) -> list[ScheduleEntry]:
        return [e for e in self.entries if e.action == "order"]


_PERIOD_DAYS: dict[str, float] = {"D": 1.0, "W": 7.0, "M": 30.0}


def _next_period(d: Date, frequency: str, n: int = 1) -> Date:
    days = _PERIOD_DAYS[frequency]
    return d + timedelta(days=int(days * n))


def generate_qr_schedule(
    sku_id: str,
    forecast_point: np.ndarray,
    starting_on_hand: float,
    Q: float,
    R: float,
    lead_time_days: float,
    frequency: Literal["D", "W", "M"],
    start_date: Date,
) -> Schedule:
    """(Q,R) continuous review: order Q whenever projected on-hand falls to R."""
    h = len(forecast_point)
    period_days = _PERIOD_DAYS[frequency]
    lead_periods = max(1, int(round(lead_time_days / period_days)))

    on_hand = float(starting_on_hand)
    entries: list[ScheduleEntry] = []
    pending: dict[int, float] = {}  # arrival_period_idx -> qty
    n_orders = 0
    total_qty = 0.0
    stockout_periods = 0

    for t in range(h):
        d = forecast_point[t]
        on_hand_after_demand = max(0.0, on_hand - d)
        if on_hand < d:
            stockout_periods += 1
        on_hand = on_hand_after_demand

        delivery = pending.pop(t, 0.0)
        on_hand_after_delivery = on_hand + delivery

        action = "no_op"
        reason = None
        qty = 0.0
        expected_arrival = None
        if delivery > 0:
            action = "delivery"
            reason = f"delivery of {delivery:.0f} units"
        elif on_hand_after_delivery <= R:
            arrival_idx = t + lead_periods
            if arrival_idx < h and arrival_idx not in pending:
                pending[arrival_idx] = Q
                action = "order"
                qty = Q
                expected_arrival = _next_period(start_date, frequency, arrival_idx).isoformat()
                reason = f"on-hand {on_hand_after_delivery:.0f} ≤ R={R:.0f}"
                n_orders += 1
                total_qty += Q

        entries.append(ScheduleEntry(
            period_idx=t,
            date=_next_period(start_date, frequency, t).isoformat(),
            action=action,  # type: ignore[arg-type]
            qty=qty,
            expected_on_hand_after_demand=on_hand_after_demand,
            expected_on_hand_after_delivery=on_hand_after_delivery,
            expected_arrival=expected_arrival,
            reason=reason,
        ))
        on_hand = on_hand_after_delivery

    return Schedule(
        sku_id=sku_id, horizon_periods=h, frequency=frequency,
        starting_on_hand=starting_on_hand, entries=entries,
        n_orders=n_orders, total_units_ordered=total_qty,
        expected_stockout_periods=stockout_periods,
    )


def generate_ss_schedule(
    sku_id: str,
    forecast_point: np.ndarray,
    starting_on_hand: float,
    s: float,
    S: float,
    review_period_periods: int,
    lead_time_days: float,
    frequency: Literal["D", "W", "M"],
    start_date: Date,
) -> Schedule:
    """(s,S) periodic review: every review_period, if on-hand ≤ s, order up to S."""
    h = len(forecast_point)
    period_days = _PERIOD_DAYS[frequency]
    lead_periods = max(1, int(round(lead_time_days / period_days)))

    on_hand = float(starting_on_hand)
    entries: list[ScheduleEntry] = []
    pending: dict[int, float] = {}
    n_orders = 0
    total_qty = 0.0
    stockout_periods = 0

    for t in range(h):
        d = forecast_point[t]
        on_hand_after_demand = max(0.0, on_hand - d)
        if on_hand < d:
            stockout_periods += 1
        on_hand = on_hand_after_demand

        delivery = pending.pop(t, 0.0)
        on_hand_after_delivery = on_hand + delivery

        action = "no_op"
        reason = None
        qty = 0.0
        expected_arrival = None
        if delivery > 0:
            action = "delivery"
            reason = f"delivery of {delivery:.0f} units"
        elif t % review_period_periods == 0 and on_hand_after_delivery <= s:
            order_qty = max(0.0, S - on_hand_after_delivery - sum(pending.values()))
            arrival_idx = t + lead_periods
            if order_qty > 0 and arrival_idx < h:
                pending[arrival_idx] = pending.get(arrival_idx, 0.0) + order_qty
                action = "order"
                qty = order_qty
                expected_arrival = _next_period(start_date, frequency, arrival_idx).isoformat()
                reason = f"review @ t={t}: on-hand {on_hand_after_delivery:.0f} ≤ s={s:.0f}, order to S={S:.0f}"
                n_orders += 1
                total_qty += order_qty

        entries.append(ScheduleEntry(
            period_idx=t,
            date=_next_period(start_date, frequency, t).isoformat(),
            action=action,  # type: ignore[arg-type]
            qty=qty,
            expected_on_hand_after_demand=on_hand_after_demand,
            expected_on_hand_after_delivery=on_hand_after_delivery,
            expected_arrival=expected_arrival,
            reason=reason,
        ))
        on_hand = on_hand_after_delivery

    return Schedule(
        sku_id=sku_id, horizon_periods=h, frequency=frequency,
        starting_on_hand=starting_on_hand, entries=entries,
        n_orders=n_orders, total_units_ordered=total_qty,
        expected_stockout_periods=stockout_periods,
    )


def generate_schedule(
    sku_id: str,
    forecast_point: np.ndarray,
    starting_on_hand: float,
    policy_mode: PolicyMode,
    parameters: dict,
    lead_time_days: float,
    frequency: Literal["D", "W", "M"],
    start_date: Date,
    review_period_periods: int = 1,
) -> Schedule:
    """Top-level: dispatch to the right schedule generator based on policy."""
    if policy_mode == "QR":
        return generate_qr_schedule(
            sku_id=sku_id,
            forecast_point=forecast_point,
            starting_on_hand=starting_on_hand,
            Q=float(parameters["Q"]),
            R=float(parameters["R"]),
            lead_time_days=lead_time_days,
            frequency=frequency,
            start_date=start_date,
        )
    if policy_mode == "sS":
        return generate_ss_schedule(
            sku_id=sku_id,
            forecast_point=forecast_point,
            starting_on_hand=starting_on_hand,
            s=float(parameters["s"]),
            S=float(parameters["S"]),
            review_period_periods=review_period_periods,
            lead_time_days=lead_time_days,
            frequency=frequency,
            start_date=start_date,
        )
    if policy_mode == "base_stock":
        S = float(parameters["S"])
        return generate_ss_schedule(
            sku_id=sku_id,
            forecast_point=forecast_point,
            starting_on_hand=starting_on_hand,
            s=S - 1,
            S=S,
            review_period_periods=1,
            lead_time_days=lead_time_days,
            frequency=frequency,
            start_date=start_date,
        )
    raise ValueError(f"unsupported policy_mode: {policy_mode}")
