"""Service-level vs cost frontier for one SKU.

Runs the recommendation pipeline at a sweep of service levels and returns
the resulting (cost, fill_rate, inventory_$) points so the UI can plot a
Pareto frontier and let the user drag a slider to pick a target SL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.db import open_dataset
from apps.api.inventory.recommend import recommend_sku
from apps.api.inventory.schemas import RecommendationOverrides
from apps.api.inventory.settings import load_dataset_settings


SERVICE_LEVELS = [0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99]


def _newsvendor_optimal_q(unit_cost: float, unit_price: float, salvage: float, samples: np.ndarray) -> dict | None:
    cu = max(0.01, unit_price - unit_cost)
    co = max(0.01, unit_cost - salvage)
    cr = cu / (cu + co)
    q_star = float(np.quantile(samples, cr))
    return {
        "optimal_qty": q_star,
        "critical_ratio": float(cr),
        "underage_cost": float(cu),
        "overage_cost": float(co),
    }


def compute_frontier(dataset_id: str, sku_id: str) -> dict:
    """Sweep recommendations across service levels and return a frontier."""
    sku_id = sku_id.strip().upper()
    persisted = load_dataset_settings(dataset_id)
    baseline_sl = persisted.service_level

    points: list[dict] = []
    base_rec = None
    for sl in SERVICE_LEVELS:
        rec = recommend_sku(dataset_id, sku_id, overrides=RecommendationOverrides(service_level=sl))
        if base_rec is None:
            base_rec = rec
        inv_value = (rec.recommended_order_qty / 2 + rec.safety_stock)
        with open_dataset(dataset_id, read_only=True) as conn:
            uc = conn.execute(
                "SELECT unit_cost FROM panel WHERE sku_id = ? AND unit_cost IS NOT NULL ORDER BY date DESC LIMIT 1",
                [sku_id],
            ).fetchone()
        unit_cost = float(uc[0]) if uc and uc[0] is not None else 1.0
        points.append({
            "service_level": float(sl),
            "recommended_order_qty": float(rec.recommended_order_qty),
            "reorder_point": float(rec.reorder_point) if rec.reorder_point is not None else None,
            "safety_stock": float(rec.safety_stock),
            "expected_fill_rate": float(rec.expected_fill_rate),
            "expected_holding_cost_annual": float(rec.expected_holding_cost_annual),
            "expected_total_cost_annual": float(rec.expected_total_cost_annual),
            "inventory_value": float(inv_value * unit_cost),
        })

    with open_dataset(dataset_id, read_only=True) as conn:
        sku_df = conn.execute(
            "SELECT demand, unit_cost, unit_price FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id],
        ).fetchdf()
    if sku_df.empty:
        raise ValueError(f"SKU {sku_id} not found")
    unit_cost = float(sku_df["unit_cost"].dropna().iloc[-1]) if sku_df["unit_cost"].notna().any() else 1.0
    unit_price = float(sku_df["unit_price"].dropna().iloc[-1]) if sku_df["unit_price"].notna().any() else unit_cost * 1.5
    demand_samples = sku_df["demand"].astype(float).to_numpy()
    newsvendor = _newsvendor_optimal_q(unit_cost, unit_price, salvage=0.0, samples=demand_samples)

    return {
        "sku_id": sku_id,
        "policy_name": (base_rec.policy_name if base_rec else "(s,S)"),
        "unit_cost": unit_cost,
        "unit_price": unit_price,
        "baseline_service_level": float(baseline_sl),
        "points": points,
        "newsvendor": newsvendor,
    }
