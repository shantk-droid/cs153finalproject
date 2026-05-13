"""Recommendation orchestrator: forecast → LTD distribution → policy selection → output."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from apps.api.config import get_settings
from apps.api.db import open_dataset
from apps.api.forecasting.classical import QUANTILES
from apps.api.forecasting.forecast import forecast_sku
from apps.api.inventory.abc_xyz import classify_abc_xyz
from apps.api.inventory.distributions import (
    fit_lead_time_gamma,
    integrate_lead_time_demand,
)
from apps.api.inventory.multi_period import generate_schedule
from apps.api.inventory.policies import (
    base_stock,
    eoq,
    newsvendor,
    qr_policy,
    ss_policy_simulated,
)
from apps.api.inventory.settings import load_dataset_settings
from apps.api.inventory.schemas import (
    PolicyName,
    Recommendation,
    RecommendationOverrides,
)
from apps.api.ingestion.validators import infer_frequency

FREQ_TO_DAYS = {"D": 1.0, "W": 7.0, "M": 30.0}
FREQ_TO_ANNUALIZATION = {"D": 365.0, "W": 52.0, "M": 12.0}


def _load_category_defaults() -> dict:
    settings = get_settings()
    path = settings.m5_artifacts_path / "category_defaults.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _category_for_sku(category: str | None, defaults: dict) -> dict:
    if category and category in defaults:
        return defaults[category]
    if category:
        for k in defaults:
            if k.startswith(category.split("_")[0].upper()):
                return defaults[k]
    return defaults.get("_default", {
        "holding_cost_rate": 0.25,
        "order_cost_default": 50,
        "markup_default": 1.5,
        "default_lead_time_days": 14,
        "perishable": False,
        "review_period_default_days": 14,
        "avg_unit_price_m5": 5.0,
    })


def _select_policy(category: str | None, defaults: dict, characterization: str,
                   overrides: RecommendationOverrides) -> PolicyName:
    if overrides.policy_override:
        return overrides.policy_override
    cat_def = _category_for_sku(category, defaults)
    if cat_def.get("perishable", False):
        return "newsvendor"
    return "(s,S)"


def _stockout_aware_service_level(
    overrides: RecommendationOverrides,
    unit_price: float,
    unit_cost: float,
    holding_cost_per_unit: float,
) -> float:
    """If the user hasn't pinned service_level, derive the implied newsvendor-optimal level
    from the stockout : holding cost ratio:
        alpha* = Cu / (Cu + Co)
    where Cu = lost margin per unit, Co = holding cost per unit per review period (≈ a year
    proxy here). Caps the result in [0.85, 0.99] so we don't go wild on extreme ratios.
    """
    if overrides.service_level is not None:
        return overrides.service_level
    underage = max(0.5, unit_price - unit_cost)
    overage = max(0.5, holding_cost_per_unit)
    alpha = underage / (underage + overage)
    return float(min(0.99, max(0.85, alpha)))


def recommend_sku(
    dataset_id: str,
    sku_id: str,
    overrides: RecommendationOverrides | None = None,
) -> Recommendation:
    overrides = overrides or RecommendationOverrides()

    with open_dataset(dataset_id, read_only=True) as conn:
        sku_df = conn.execute(
            "SELECT * FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id.strip().upper()],
        ).fetchdf()
        full_panel = conn.execute("SELECT * FROM panel").fetchdf()

    if sku_df.empty:
        raise ValueError(f"sku '{sku_id}' has no history")

    frequency = infer_frequency(sku_df["date"]) or "W"
    period_days = FREQ_TO_DAYS[frequency]
    annualization = FREQ_TO_ANNUALIZATION[frequency]

    horizon = overrides.horizon_periods or 12
    forecast = forecast_sku(dataset_id, sku_id, horizon=horizon, n_backtest_folds=2)

    quantiles_arr = {q: np.array(forecast.quantiles[str(q)]) for q in QUANTILES}
    period_demand_mean = float(np.mean(forecast.point))
    annual_demand = period_demand_mean * annualization

    defaults = _load_category_defaults()
    category = sku_df["category"].iloc[0] if "category" in sku_df.columns else None
    cat_def = _category_for_sku(category, defaults)

    persisted = load_dataset_settings(dataset_id)
    unit_cost = float(sku_df["unit_cost"].dropna().mean()) if sku_df["unit_cost"].notna().any() else 1.0
    unit_price = float(sku_df["unit_price"].dropna().mean()) if sku_df["unit_price"].notna().any() else unit_cost * cat_def.get("markup_default", 1.5)
    holding_cost_rate = overrides.holding_cost_rate or persisted.holding_cost_rate or cat_def.get("holding_cost_rate", 0.25)
    holding_cost_per_unit = holding_cost_rate * unit_cost
    order_cost = overrides.order_cost or persisted.order_cost or cat_def.get("order_cost_default", 50.0)
    if overrides.service_level is None and persisted.service_level != 0.95:
        # User saved a non-default service level → respect it
        service_level = persisted.service_level
    else:
        service_level = _stockout_aware_service_level(overrides, unit_price, unit_cost, holding_cost_per_unit)

    if overrides.lead_time_days_override is not None:
        lt_mean = overrides.lead_time_days_override
        lt_shape, lt_scale = (max(1.0, (lt_mean / 0.2) ** 2 / lt_mean), max(1e-3, lt_mean * 0.04))
    else:
        lt_obs = sku_df["lead_time_days"] if "lead_time_days" in sku_df.columns else pd.Series(dtype=float)
        lt_shape, lt_scale = fit_lead_time_gamma(
            lt_obs,
            fallback_mean=cat_def.get("default_lead_time_days", 14.0),
            fallback_cv=0.2,
        )

    ltd = integrate_lead_time_demand(
        quantiles_per_period=quantiles_arr,
        period_length_days=period_days,
        lead_time_shape=lt_shape,
        lead_time_scale=lt_scale,
        n_samples=4000,
        seed=hash(sku_id) % (2**31),
    )

    abc_xyz = {a.sku_id: a for a in classify_abc_xyz(full_panel, annualization_factor=annualization)}
    sku_assignment = abc_xyz.get(sku_id.strip().upper())
    abc_class = sku_assignment.abc if sku_assignment else "C"
    xyz_class = sku_assignment.xyz if sku_assignment else "Z"

    policy = _select_policy(category, defaults, forecast.diagnostics.characterization, overrides)

    parameters: dict
    recommended_qty = 0.0
    reorder_point: float | None = None
    safety = 0.0
    p_stockout = 0.0
    fill_rate = 1.0
    holding_annual = 0.0
    total_cost_annual = 0.0
    caveats = list(forecast.caveats)

    if policy == "(Q,R)":
        res = qr_policy(ltd.samples, annual_demand, order_cost, holding_cost_per_unit, service_level)
        parameters = {"Q": res.Q, "R": res.R}
        recommended_qty = res.Q
        reorder_point = res.R
        safety = res.safety_stock
        p_stockout = res.expected_stockout_prob
        fill_rate = res.expected_fill_rate
        holding_annual = res.expected_holding_cost_annual
        total_cost_annual = res.expected_total_cost_annual

    elif policy == "EOQ":
        res = eoq(annual_demand, order_cost, holding_cost_per_unit)
        parameters = {"Q": res.Q, "expected_orders_per_year": res.expected_orders_per_year}
        recommended_qty = res.Q
        holding_annual = res.expected_holding_cost_annual
        total_cost_annual = res.total_cost_annual
        caveats.append("EOQ assumes deterministic lead time; switch to (Q,R) for stochastic.")

    elif policy == "newsvendor":
        underage = unit_price - unit_cost
        overage = holding_cost_per_unit
        if underage <= 0:
            caveats.append("price <= cost — newsvendor underage cost is non-positive; using a $1 floor.")
            underage = 1.0
        res = newsvendor(ltd.samples, underage, overage)
        parameters = {"Q": res.Q, "underage_cost": underage, "overage_cost": overage}
        recommended_qty = res.Q
        reorder_point = res.Q
        total_cost_annual = res.expected_total_cost
        p_stockout = float(np.mean(ltd.samples > res.Q))
        fill_rate = 1.0 - float(np.mean(np.maximum(ltd.samples - res.Q, 0))) / max(1e-9, float(np.mean(ltd.samples)))
        fill_rate = max(0.0, min(1.0, fill_rate))

    elif policy == "(s,S)":
        from apps.api.inventory.distributions import sample_demand_per_period
        rng_for_ss = np.random.default_rng(hash(sku_id + "ss") % (2**31))
        demand_period_samples = sample_demand_per_period(quantiles_arr, n_samples=2000, rng=rng_for_ss).flatten()
        lt_period_mean = max(1.0, lt_shape * lt_scale / period_days)
        leadtime_period_samples = rng_for_ss.gamma(shape=lt_shape, scale=lt_scale, size=1000) / period_days
        leadtime_period_samples = np.maximum(1.0, leadtime_period_samples)
        review_period = max(1, int(round(cat_def.get("review_period_default_days", 14) / period_days)))
        sim_horizon = max(26, horizon * 4)
        res = ss_policy_simulated(
            demand_period_samples=demand_period_samples,
            leadtime_period_samples=leadtime_period_samples,
            review_period=review_period,
            service_level=service_level,
            holding_cost_per_unit=holding_cost_per_unit,
            order_cost=order_cost,
            annual_demand=annual_demand,
            horizon_periods=sim_horizon,
            n_replications=80,
        )
        parameters = {"s": res.s, "S": res.S, "review_period_periods": review_period}
        on_hand_for_qty = sku_df["on_hand"].dropna().iloc[-1] if sku_df["on_hand"].notna().any() else 0.0
        recommended_qty = max(0.0, res.S - float(on_hand_for_qty))
        reorder_point = res.s
        safety = max(0.0, res.s - ltd.mean)
        p_stockout = res.expected_stockout_prob
        fill_rate = res.expected_fill_rate
        holding_annual = (res.S / 2.0 + safety) * holding_cost_per_unit
        total_cost_annual = holding_annual + (annual_demand / max(res.S - res.s, 1.0)) * order_cost

    else:  # base-stock
        res = base_stock(ltd.samples, service_level)
        parameters = {"S": res.S}
        recommended_qty = res.S
        reorder_point = res.S
        safety = res.safety_stock
        p_stockout = res.expected_stockout_prob
        fill_rate = 1.0 - p_stockout
        holding_annual = res.S * holding_cost_per_unit
        total_cost_annual = holding_annual

    on_hand_now = float(sku_df["on_hand"].dropna().iloc[-1]) if sku_df["on_hand"].notna().any() else 0.0
    if reorder_point is not None and on_hand_now > reorder_point and policy in ("(Q,R)", "(s,S)", "base-stock"):
        recommended_qty = 0.0
        caveats.append(f"on-hand {on_hand_now:.0f} > reorder point {reorder_point:.0f}; no order needed now.")

    schedule_entries: list[dict] | None = None
    if policy in ("(Q,R)", "(s,S)", "base-stock"):
        try:
            policy_mode = {"(Q,R)": "QR", "(s,S)": "sS", "base-stock": "base_stock"}[policy]
            schedule = generate_schedule(
                sku_id=sku_id.strip().upper(),
                forecast_point=np.array(forecast.point),
                starting_on_hand=on_hand_now,
                policy_mode=policy_mode,  # type: ignore[arg-type]
                parameters={k: float(v) if isinstance(v, (int, float, np.floating)) else v for k, v in parameters.items()},
                lead_time_days=lt_shape * lt_scale,
                frequency=frequency,
                start_date=sku_df["date"].max().date(),
                review_period_periods=int(parameters.get("review_period_periods", 1)) if isinstance(parameters.get("review_period_periods"), (int, float)) else 1,
            )
            schedule_entries = [
                {
                    "period_idx": e.period_idx, "date": e.date, "action": e.action,
                    "qty": round(e.qty, 1),
                    "expected_on_hand_after_demand": round(e.expected_on_hand_after_demand, 1),
                    "expected_on_hand_after_delivery": round(e.expected_on_hand_after_delivery, 1),
                    "expected_arrival": e.expected_arrival,
                    "reason": e.reason,
                } for e in schedule.entries
            ]
            if schedule.expected_stockout_periods > 0:
                caveats.append(
                    f"projected schedule has {schedule.expected_stockout_periods} stockout periods "
                    f"out of {schedule.horizon_periods}; consider higher service level or shorter lead time."
                )
        except Exception as e:
            caveats.append(f"schedule generation failed: {type(e).__name__}: {e}")

    return Recommendation(
        sku_id=sku_id.strip().upper(),
        policy_name=policy,
        parameters={k: float(v) if isinstance(v, (int, float, np.floating)) else v for k, v in parameters.items()},
        recommended_order_qty=float(recommended_qty),
        reorder_point=float(reorder_point) if reorder_point is not None else None,
        safety_stock=float(safety),
        expected_stockout_prob=float(p_stockout),
        expected_fill_rate=float(fill_rate),
        expected_holding_cost_annual=float(holding_annual),
        expected_total_cost_annual=float(total_cost_annual),
        abc_class=abc_class,
        xyz_class=xyz_class,
        schedule=schedule_entries,
        joint_replen_group=None,
        caveats=caveats,
    )


def _plan_item_rationale(item) -> str:
    """One-line explanation of why this SKU made the plan. Cheap, no LLM call.

    Composed from the queue-item fields the analytical scorer already produced —
    stockout prob, expedite, projected stockout date, revenue-at-risk, ABC class.
    """
    parts: list[str] = []
    if item.stockout_prob > 0.5:
        parts.append(f"high stockout risk ({item.stockout_prob:.0%})")
    elif item.stockout_prob > 0.2:
        parts.append(f"moderate stockout risk ({item.stockout_prob:.0%})")
    if item.expedite_flag:
        parts.append("expedite recommended")
    if item.projected_stockout_date:
        parts.append(f"projected stockout {item.projected_stockout_date}")
    if item.revenue_at_risk and item.revenue_at_risk > 0:
        parts.append(f"${item.revenue_at_risk:.0f} revenue at risk")
    if item.abc_class == "A":
        parts.append("A-class SKU")
    return "; ".join(parts) or "queue-flagged for replenishment"


def plan_reorder_week(
    dataset_id: str,
    service_level: float = 0.95,
    budget_cap_usd: float | None = None,
    top_n: int = 25,
) -> dict:
    """Build a one-week reorder plan for the most urgent SKUs in the dataset.

    Ranks candidates via the existing reorder-queue scorer (stockout-prob × revenue-at-risk,
    analytical — no per-SKU forecast call). When `budget_cap_usd` is set, picks greedily by
    risk-per-dollar so the cap is respected; items that don't fit are returned in
    `deferred_items` with a reason. Without a budget cap, returns the top `top_n` by score.

    The `service_level` param is informational — the queue's qty assumes a 95% default
    internally; pass-through here so the chat agent can frame the plan ("at 95% service
    commitment, here's the plan"). Recomputing per SKU at a custom service level would
    require N forecast calls — out of scope for v1.
    """
    from apps.api.inventory.reorder_queue import compute_reorder_queue

    candidates = compute_reorder_queue(dataset_id, limit=max(top_n * 3, 100))
    candidates = [c for c in candidates if c.recommended_qty > 0]

    items_in_plan: list = []
    deferred: list[tuple] = []

    if budget_cap_usd is not None and budget_cap_usd > 0:
        sorted_by_efficiency = sorted(
            candidates,
            key=lambda i: (i.score / max(1.0, i.total_cost), i.score),
            reverse=True,
        )
        spent = 0.0
        for item in sorted_by_efficiency:
            if len(items_in_plan) >= top_n:
                deferred.append((item, "top_n_cap_reached"))
                continue
            if spent + item.total_cost <= budget_cap_usd:
                items_in_plan.append(item)
                spent += item.total_cost
            else:
                deferred.append((item, "budget_exceeded"))
    else:
        items_in_plan = candidates[:top_n]
        deferred = [(c, "top_n_cap_reached") for c in candidates[top_n:]]

    total_cost = sum(i.total_cost for i in items_in_plan)
    budget_used_pct: float | None = None
    if budget_cap_usd and budget_cap_usd > 0:
        budget_used_pct = round(total_cost / budget_cap_usd * 100.0, 1)

    return {
        "horizon_days": 7,
        "service_level": service_level,
        "items": [
            {
                "sku_id": i.sku_id,
                "supplier_name": i.supplier_name,
                "supplier_id": i.supplier_id,
                "qty": round(i.recommended_qty, 1),
                "unit_cost": round(i.unit_cost, 2) if i.unit_cost else None,
                "expected_cost": round(i.total_cost, 2),
                "expected_revenue_at_risk": round(i.revenue_at_risk, 2) if i.revenue_at_risk else 0.0,
                "stockout_prob": round(i.stockout_prob, 3),
                "projected_stockout_date": i.projected_stockout_date,
                "score": round(i.score, 3),
                "expedite_flag": i.expedite_flag,
                "abc_class": i.abc_class,
                "xyz_class": i.xyz_class,
                "joint_replen_group": i.joint_replen_group,
                "rationale": _plan_item_rationale(i),
            }
            for i in items_in_plan
        ],
        "total_cost_usd": round(total_cost, 2),
        "budget_cap_usd": budget_cap_usd,
        "budget_used_pct": budget_used_pct,
        "deferred_items": [
            {
                "sku_id": i.sku_id,
                "supplier_name": i.supplier_name,
                "expected_cost": round(i.total_cost, 2),
                "reason": reason,
            }
            for i, reason in deferred
        ],
        "n_candidates_evaluated": len(candidates),
    }
