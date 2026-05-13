"""Joint replenishment recommender.

For SKUs sharing a supplier, group their reorder timing into a common cadence to share
fixed costs. Two-tier algorithm:

1. Compute each SKU's optimal individual cycle T_i = Q_i / D_i (days/order) from EOQ.
2. Within each supplier, hierarchical-cluster SKUs whose individual cycles fall within
   ±tolerance of a common cadence. Members of a cluster share an order cadence T_cluster
   = mean of their individual cycles.

Estimated savings: each pooled order saves (n_members - 1) × order_cost per cycle.

Output is a list of `JointReplenGroup`s — supplier + cadence + members + savings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class JointReplenMember:
    sku_id: str
    individual_cycle_days: float
    annual_demand: float
    eoq: float


@dataclass
class JointReplenGroup:
    supplier: str
    group_id: str
    cadence_days: float
    members: list[JointReplenMember]
    annual_orders_pooled: float
    annual_orders_individual: float
    annual_savings_usd: float
    note: str | None = None


def _eoq_cycle_days(annual_demand: float, order_cost: float, holding_cost_per_unit: float) -> tuple[float, float]:
    if annual_demand <= 0 or order_cost <= 0 or holding_cost_per_unit <= 0:
        return 0.0, 0.0
    Q = math.sqrt(2.0 * annual_demand * order_cost / holding_cost_per_unit)
    cycle_days = (Q / annual_demand) * 365.0 if annual_demand > 0 else 0.0
    return Q, cycle_days


def _cluster_cycles(cycles: np.ndarray, tolerance: float = 0.20) -> list[list[int]]:
    """Greedy single-link clustering on sorted cycles. Two cycles cluster if within ±tolerance."""
    n = len(cycles)
    if n == 0:
        return []
    order = np.argsort(cycles)
    sorted_cycles = cycles[order]
    clusters: list[list[int]] = [[int(order[0])]]
    cluster_means = [float(sorted_cycles[0])]
    for i in range(1, n):
        cur = float(sorted_cycles[i])
        last_mean = cluster_means[-1]
        if last_mean > 0 and abs(cur - last_mean) / last_mean <= tolerance:
            clusters[-1].append(int(order[i]))
            cluster_means[-1] = float(np.mean([cycles[j] for j in clusters[-1]]))
        else:
            clusters.append([int(order[i])])
            cluster_means.append(cur)
    return clusters


def recommend_joint_replenishment(
    panel: pd.DataFrame,
    annualization_factor: float,
    order_cost_default: float,
    holding_cost_rate_default: float,
    cycle_tolerance: float = 0.20,
    min_group_size: int = 2,
) -> list[JointReplenGroup]:
    """Find joint-replenishment opportunities across the panel.

    Args:
        panel: canonical panel with sku_id, demand, supplier, unit_cost.
        annualization_factor: e.g. 52 for weekly data.
        order_cost_default, holding_cost_rate_default: fall-back economic params per SKU.
        cycle_tolerance: SKUs cluster if their cycles are within ±tolerance fraction.
        min_group_size: don't recommend a group smaller than this (n=1 = nothing to pool).
    """
    if panel.empty or "supplier" not in panel.columns:
        return []

    by_sku = panel.groupby("sku_id").agg(
        supplier=("supplier", "first"),
        mean_demand=("demand", "mean"),
        unit_cost=("unit_cost", "mean") if "unit_cost" in panel.columns else ("demand", "mean"),
    ).reset_index().dropna(subset=["supplier"])
    by_sku["unit_cost"] = by_sku["unit_cost"].fillna(1.0).clip(lower=0.5)
    by_sku["annual_demand"] = (by_sku["mean_demand"].fillna(0.0) * annualization_factor).clip(lower=0.0)

    out: list[JointReplenGroup] = []
    for supplier, g in by_sku.groupby("supplier"):
        if len(g) < min_group_size:
            continue
        members_data = []
        for _, row in g.iterrows():
            holding_per_unit = max(0.5, holding_cost_rate_default * float(row["unit_cost"]))
            Q, cycle = _eoq_cycle_days(float(row["annual_demand"]), order_cost_default, holding_per_unit)
            if cycle <= 0:
                continue
            members_data.append(JointReplenMember(
                sku_id=str(row["sku_id"]),
                individual_cycle_days=cycle,
                annual_demand=float(row["annual_demand"]),
                eoq=Q,
            ))
        if len(members_data) < min_group_size:
            continue

        cycles = np.array([m.individual_cycle_days for m in members_data])
        clusters = _cluster_cycles(cycles, tolerance=cycle_tolerance)

        for ci, idx_list in enumerate(clusters):
            if len(idx_list) < min_group_size:
                continue
            cluster_members = [members_data[i] for i in idx_list]
            cadence_days = float(np.mean([m.individual_cycle_days for m in cluster_members]))
            annual_orders_pooled = 365.0 / cadence_days if cadence_days > 0 else 0.0
            annual_orders_individual = sum(
                365.0 / m.individual_cycle_days for m in cluster_members if m.individual_cycle_days > 0
            )
            savings = max(0.0, (annual_orders_individual - annual_orders_pooled) * order_cost_default)

            out.append(JointReplenGroup(
                supplier=str(supplier),
                group_id=f"{supplier}-cluster-{ci}",
                cadence_days=cadence_days,
                members=cluster_members,
                annual_orders_pooled=annual_orders_pooled,
                annual_orders_individual=annual_orders_individual,
                annual_savings_usd=savings,
                note=(
                    f"{len(cluster_members)} SKUs from {supplier} can be pooled at a "
                    f"{cadence_days:.0f}-day cadence; saves ~${savings:.0f}/yr in fixed order cost."
                ),
            ))

    return out
