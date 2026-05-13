"""Stress test: shock lead time + demand, recompute exposure portfolio-wide.

Uses the analytical reorder queue scoring (fast) at both baseline and shock,
returns deltas + 95th-percentile revenue at risk (VaR / CVaR).
"""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

from apps.api.db import open_dataset
from apps.api.ingestion.validators import infer_frequency

FREQ_TO_DAYS = {"D": 1.0, "W": 7.0, "M": 30.0}


def _per_sku_exposure(
    panel: pd.DataFrame,
    suppliers_df: pd.DataFrame,
    period_days: float,
    lt_mult: float,
    demand_mult: float,
    sl: float | None,
) -> dict[str, dict]:
    by_sup = {row["name"]: row for _, row in suppliers_df.iterrows()} if not suppliers_df.empty else {}
    out: dict[str, dict] = {}
    target_sl = sl if sl is not None else 0.95

    for sku_id, sub in panel.groupby("sku_id"):
        sub = sub.sort_values("date")
        if len(sub) < 4:
            continue
        recent = sub.tail(min(13, len(sub)))
        mean_d = float(recent["demand"].mean()) * demand_mult
        std_d = max(0.5, float(recent["demand"].std(ddof=0))) * demand_mult
        on_hand_series = sub["on_hand"].dropna()
        if on_hand_series.empty:
            continue
        on_hand = float(on_hand_series.iloc[-1])
        unit_cost = float(sub["unit_cost"].dropna().iloc[-1]) if sub["unit_cost"].notna().any() else 1.0
        unit_price = float(sub["unit_price"].dropna().iloc[-1]) if sub["unit_price"].notna().any() else unit_cost * 1.5

        sup_name = sub["supplier"].iloc[-1] if "supplier" in sub.columns else None
        sup = by_sup.get(sup_name) if sup_name else None
        lt_obs = sub["lead_time_days"].dropna() if "lead_time_days" in sub.columns else pd.Series(dtype=float)
        if not lt_obs.empty:
            lt_mean = float(lt_obs.mean()) * lt_mult
            lt_std = float(lt_obs.std(ddof=0)) if len(lt_obs) > 1 else max(lt_mean * 0.2, 0.5)
        elif sup is not None and pd.notna(sup["default_lead_time_days"]):
            lt_mean = float(sup["default_lead_time_days"]) * lt_mult
            lt_std = float(sup["lead_time_std_days"]) if pd.notna(sup["lead_time_std_days"]) else max(lt_mean * 0.2, 0.5)
        else:
            lt_mean = 14.0 * lt_mult
            lt_std = 2.8

        lt_periods = max(1.0, lt_mean / period_days)
        ltd_mean = lt_periods * mean_d
        ltd_var = lt_periods * std_d * std_d + (mean_d * mean_d) * (lt_std / period_days) ** 2
        ltd_std = math.sqrt(max(ltd_var, 1e-9))

        target_oh = ltd_mean + norm.ppf(target_sl) * ltd_std
        z = (on_hand - ltd_mean) / max(ltd_std, 1e-6)
        stockout_prob = float(1.0 - norm.cdf(z))
        revenue_at_risk = float(stockout_prob * mean_d * unit_price * lt_periods)
        recommended = max(0.0, target_oh - on_hand)

        out[sku_id] = {
            "stockout_prob": stockout_prob,
            "revenue_at_risk": revenue_at_risk,
            "recommended_qty": recommended,
        }
    return out


def run_stress_test(
    dataset_id: str,
    lead_time_multiplier: float = 1.0,
    demand_multiplier: float = 1.0,
    service_level: float | None = None,
) -> dict:
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel").fetchdf()
        suppliers_df = conn.execute("SELECT * FROM suppliers").fetchdf()

    if panel.empty:
        return {
            "baseline_total_revenue_at_risk": 0.0,
            "shock_total_revenue_at_risk": 0.0,
            "delta_total_revenue_at_risk": 0.0,
            "baseline_n_at_risk": 0,
            "shock_n_at_risk": 0,
            "var_95": 0.0,
            "cvar_95": 0.0,
            "top_impacted": [],
        }

    frequency = infer_frequency(panel["date"]) or "W"
    period_days = FREQ_TO_DAYS[frequency]

    baseline = _per_sku_exposure(panel, suppliers_df, period_days, 1.0, 1.0, service_level)
    shock = _per_sku_exposure(panel, suppliers_df, period_days, lead_time_multiplier, demand_multiplier, service_level)

    impact_rows: list[dict] = []
    for sku in shock:
        b = baseline.get(sku, {"stockout_prob": 0.0, "revenue_at_risk": 0.0, "recommended_qty": 0.0})
        s = shock[sku]
        impact_rows.append({
            "sku_id": sku,
            "baseline_stockout_prob": b["stockout_prob"],
            "shock_stockout_prob": s["stockout_prob"],
            "baseline_revenue_at_risk": b["revenue_at_risk"],
            "shock_revenue_at_risk": s["revenue_at_risk"],
            "delta_revenue_at_risk": s["revenue_at_risk"] - b["revenue_at_risk"],
            "baseline_recommended_qty": b["recommended_qty"],
            "shock_recommended_qty": s["recommended_qty"],
        })

    base_total = sum(b["revenue_at_risk"] for b in baseline.values())
    shock_total = sum(s["revenue_at_risk"] for s in shock.values())
    base_n = sum(1 for b in baseline.values() if b["stockout_prob"] > 0.1)
    shock_n = sum(1 for s in shock.values() if s["stockout_prob"] > 0.1)

    arr = np.array([s["revenue_at_risk"] for s in shock.values()])
    var_95 = float(np.quantile(arr, 0.95)) if arr.size else 0.0
    above_var = arr[arr >= var_95]
    cvar_95 = float(above_var.mean()) if above_var.size else 0.0

    impact_rows.sort(key=lambda r: r["delta_revenue_at_risk"], reverse=True)

    return {
        "baseline_total_revenue_at_risk": float(base_total),
        "shock_total_revenue_at_risk": float(shock_total),
        "delta_total_revenue_at_risk": float(shock_total - base_total),
        "baseline_n_at_risk": int(base_n),
        "shock_n_at_risk": int(shock_n),
        "var_95": var_95,
        "cvar_95": cvar_95,
        "top_impacted": impact_rows[:10],
    }
