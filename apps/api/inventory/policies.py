"""Inventory policies — pure functions, easy to test.

All policies operate on the LTD distribution (not normal approximation) where possible.
The output of each function is a small dataclass; the routes/recommend orchestrator
converts to the canonical Recommendation pydantic model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class EOQResult:
    Q: float
    expected_orders_per_year: float
    expected_holding_cost_annual: float
    expected_order_cost_annual: float
    total_cost_annual: float


@dataclass
class QRResult:
    Q: float
    R: float
    safety_stock: float
    expected_stockout_prob: float
    expected_fill_rate: float
    expected_holding_cost_annual: float
    expected_total_cost_annual: float


@dataclass
class SSResult:
    s: float
    S: float
    expected_stockout_prob: float
    expected_fill_rate: float


@dataclass
class NewsvendorResult:
    Q: float
    expected_underage_cost: float
    expected_overage_cost: float
    expected_total_cost: float


@dataclass
class BaseStockResult:
    S: float
    safety_stock: float
    expected_stockout_prob: float


# ---------- EOQ ----------

def eoq(annual_demand: float, order_cost: float, holding_cost_per_unit: float) -> EOQResult:
    """Q* = sqrt(2 D K / h). Returns full breakdown of expected costs at Q*."""
    if annual_demand <= 0 or order_cost <= 0 or holding_cost_per_unit <= 0:
        raise ValueError("eoq inputs must all be positive")
    q = math.sqrt(2.0 * annual_demand * order_cost / holding_cost_per_unit)
    n_orders = annual_demand / q
    holding = (q / 2.0) * holding_cost_per_unit
    ordering = n_orders * order_cost
    return EOQResult(
        Q=q,
        expected_orders_per_year=n_orders,
        expected_holding_cost_annual=holding,
        expected_order_cost_annual=ordering,
        total_cost_annual=holding + ordering,
    )


# ---------- (Q, R) continuous review ----------

def qr_policy(
    ltd_samples: np.ndarray,
    annual_demand: float,
    order_cost: float,
    holding_cost_per_unit: float,
    service_level: float = 0.95,
) -> QRResult:
    """(Q, R) where Q from EOQ, R = quantile(LTD, service_level).

    Stockout probability = P(LTD > R).
    Fill rate = 1 - E[max(LTD - R, 0)] / mean(LTD), with the expected shortage from samples.
    """
    if not (0.0 < service_level < 1.0):
        raise ValueError("service_level must be in (0, 1)")

    eoq_res = eoq(annual_demand, order_cost, holding_cost_per_unit)
    q = eoq_res.Q
    r = float(np.quantile(ltd_samples, service_level))
    mean_ltd = float(np.mean(ltd_samples))
    safety = max(0.0, r - mean_ltd)

    p_stockout = float(np.mean(ltd_samples > r))
    expected_shortage = float(np.mean(np.maximum(ltd_samples - r, 0.0)))
    fill_rate = 1.0 - (expected_shortage / mean_ltd) if mean_ltd > 0 else 1.0
    fill_rate = float(max(0.0, min(1.0, fill_rate)))

    n_cycles = annual_demand / q if q > 0 else 0.0
    holding_annual = (q / 2.0 + safety) * holding_cost_per_unit
    ordering_annual = n_cycles * order_cost
    total_cost = holding_annual + ordering_annual

    return QRResult(
        Q=q,
        R=r,
        safety_stock=safety,
        expected_stockout_prob=p_stockout,
        expected_fill_rate=fill_rate,
        expected_holding_cost_annual=holding_annual,
        expected_total_cost_annual=total_cost,
    )


# ---------- (s, S) periodic review by simulation ----------

def ss_policy_simulated(
    demand_period_samples: np.ndarray,
    leadtime_period_samples: np.ndarray,
    review_period: int,
    service_level: float,
    holding_cost_per_unit: float,
    order_cost: float,
    annual_demand: float,
    horizon_periods: int = 52,
    n_replications: int = 200,
    seed: int = 0,
) -> SSResult:
    """Solve (s, S) by full forward simulation under empirical demand + LT distributions.

    Search a 6×6 grid of (s, S) pairs around the LTD mean + EOQ-derived Q, run `n_replications`
    independent Monte Carlo simulations per pair, and pick the combination with the lowest
    expected total cost subject to the cycle-service-level constraint.

    Args:
        demand_period_samples: shape (n_samples,) draws from one-period demand. Used to sample
            actual demand each simulated period.
        leadtime_period_samples: shape (n_samples,) draws from lead time *in periods*.
        review_period: review every R periods (R=1 → continuous-ish, R=52 → annual).
        service_level: cycle service level constraint (0..1).
        holding_cost_per_unit: $ per unit per year.
        order_cost: fixed $ per order.
        annual_demand: used to compute the EOQ-derived spread between s and S.

    Returns:
        SSResult with chosen (s, S) and the simulated fill rate + stockout rate.
    """
    rng = np.random.default_rng(seed)
    if demand_period_samples.ndim > 1:
        demand_period_samples = demand_period_samples.flatten()
    if len(demand_period_samples) == 0:
        raise ValueError("demand_period_samples is empty")
    if len(leadtime_period_samples) == 0:
        raise ValueError("leadtime_period_samples is empty")

    mean_period_demand = float(np.mean(demand_period_samples))
    mean_lt_periods = float(np.mean(leadtime_period_samples))
    mean_ltd = max(0.1, mean_period_demand * mean_lt_periods)
    eoq_q = math.sqrt(2.0 * max(annual_demand, 1.0) * order_cost / max(holding_cost_per_unit, 1e-6))

    s_grid = np.linspace(0.5 * mean_ltd, 2.5 * mean_ltd, 6)
    S_offset_grid = np.linspace(0.5 * eoq_q, 2.0 * eoq_q, 6)
    grid = [(float(s_val), float(s_val + dS)) for s_val in s_grid for dS in S_offset_grid]

    def simulate_pair(s_val: float, S_val: float) -> tuple[float, float, float]:
        all_costs = np.empty(n_replications)
        all_fills = np.empty(n_replications)
        all_stockout_rates = np.empty(n_replications)

        for rep in range(n_replications):
            on_hand = S_val
            pending: dict[int, float] = {}
            total_demand = 0.0
            total_filled = 0.0
            stockout_periods = 0
            cost = 0.0
            for t in range(horizon_periods):
                if t in pending:
                    on_hand += pending.pop(t)
                d = float(demand_period_samples[rng.integers(0, len(demand_period_samples))])
                total_demand += d
                served = min(on_hand, d)
                total_filled += served
                on_hand = on_hand - served
                if served < d:
                    stockout_periods += 1
                    on_hand = 0.0
                cost += on_hand * holding_cost_per_unit / 52.0
                if t % review_period == 0:
                    on_order = sum(pending.values())
                    if on_hand + on_order <= s_val:
                        qty = max(0.0, S_val - on_hand - on_order)
                        if qty > 0:
                            cost += order_cost
                            lt_periods = max(1, int(round(float(
                                leadtime_period_samples[rng.integers(0, len(leadtime_period_samples))]
                            ))))
                            arrival = t + lt_periods
                            if arrival < horizon_periods:
                                pending[arrival] = pending.get(arrival, 0.0) + qty
            all_costs[rep] = cost
            all_fills[rep] = total_filled / total_demand if total_demand > 0 else 1.0
            all_stockout_rates[rep] = stockout_periods / horizon_periods

        return float(np.mean(all_costs)), float(np.mean(all_fills)), float(np.mean(all_stockout_rates))

    best: tuple[float, float, float, float] | None = None
    best_objective = float("inf")
    for s_val, S_val in grid:
        cost, fill, stockout_rate = simulate_pair(s_val, S_val)
        penalty = 0.0 if fill >= service_level else (service_level - fill) * 1e6
        objective = cost + penalty
        if objective < best_objective:
            best_objective = objective
            best = (s_val, S_val, fill, stockout_rate)

    if best is None:
        return SSResult(s=mean_ltd, S=mean_ltd + eoq_q, expected_stockout_prob=0.5, expected_fill_rate=0.5)
    s_val, S_val, fill, stockout_rate = best
    return SSResult(s=s_val, S=S_val, expected_stockout_prob=stockout_rate, expected_fill_rate=fill)


# ---------- Newsvendor ----------

def newsvendor(
    demand_samples: np.ndarray,
    underage_cost: float,
    overage_cost: float,
) -> NewsvendorResult:
    """Q* = F^-1( Cu / (Cu + Co) ) using the empirical demand CDF."""
    if underage_cost <= 0 or overage_cost <= 0:
        raise ValueError("underage_cost and overage_cost must be positive")
    critical_ratio = underage_cost / (underage_cost + overage_cost)
    q = float(np.quantile(demand_samples, critical_ratio))
    underage = float(np.mean(np.maximum(demand_samples - q, 0.0))) * underage_cost
    overage = float(np.mean(np.maximum(q - demand_samples, 0.0))) * overage_cost
    return NewsvendorResult(
        Q=q,
        expected_underage_cost=underage,
        expected_overage_cost=overage,
        expected_total_cost=underage + overage,
    )


# ---------- Base-stock ----------

def base_stock(
    ltd_samples: np.ndarray,
    service_level: float = 0.95,
) -> BaseStockResult:
    """S = quantile(LTD, service_level). Order up to S every period."""
    if not (0.0 < service_level < 1.0):
        raise ValueError("service_level must be in (0, 1)")
    s = float(np.quantile(ltd_samples, service_level))
    safety = max(0.0, s - float(np.mean(ltd_samples)))
    p_stockout = float(np.mean(ltd_samples > s))
    return BaseStockResult(S=s, safety_stock=safety, expected_stockout_prob=p_stockout)
