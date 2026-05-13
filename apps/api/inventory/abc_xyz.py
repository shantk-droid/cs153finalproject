"""ABC/XYZ classification.

ABC: Pareto cut by annualized revenue → 80/15/5 → A/B/C.
XYZ: per-SKU coefficient of variation → low/med/high → X/Y/Z.
Surfaced as a 9-cell heatmap on the dashboard. Drives default policy + review cadence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

ABCClass = Literal["A", "B", "C"]
XYZClass = Literal["X", "Y", "Z"]

XYZ_LOW_CV = 0.5
XYZ_HIGH_CV = 1.0


@dataclass
class AbcXyzAssignment:
    sku_id: str
    abc: ABCClass
    xyz: XYZClass
    revenue_annual: float
    cv_demand: float
    revenue_share: float


def classify_abc_xyz(
    df: pd.DataFrame,
    annualization_factor: float = 52.0,
) -> list[AbcXyzAssignment]:
    """Classify each SKU.

    Args:
        df: canonical panel with columns sku_id, demand, unit_price (or fallback unit_cost).
        annualization_factor: multiplier from the panel's frequency to a year (52 for weekly).

    Returns:
        Per-SKU ABC + XYZ + supporting metrics.
    """
    price = df["unit_price"] if "unit_price" in df.columns else df.get("unit_cost", pd.Series(dtype=float))
    if price is None or price.empty:
        df = df.assign(_price=1.0)
    else:
        df = df.assign(_price=price.fillna(df.get("unit_cost", pd.Series(1.0)).fillna(1.0)))
    df = df.assign(_revenue=df["demand"] * df["_price"])

    by_sku = df.groupby("sku_id").agg(
        revenue=("_revenue", "sum"),
        mean_demand=("demand", "mean"),
        std_demand=("demand", "std"),
    ).fillna(0.0)
    n_periods = df.groupby("sku_id").size()
    by_sku["revenue_annual"] = by_sku["revenue"] / np.maximum(1, n_periods) * annualization_factor
    by_sku["cv_demand"] = by_sku["std_demand"] / by_sku["mean_demand"].replace(0, np.nan)
    by_sku["cv_demand"] = by_sku["cv_demand"].fillna(0.0)

    sorted_skus = by_sku.sort_values("revenue_annual", ascending=False)
    total_revenue = sorted_skus["revenue_annual"].sum()
    if total_revenue <= 0:
        sorted_skus["revenue_share_cum"] = 0.0
    else:
        sorted_skus["revenue_share_cum"] = sorted_skus["revenue_annual"].cumsum() / total_revenue
    sorted_skus["revenue_share"] = sorted_skus["revenue_annual"] / max(total_revenue, 1e-9)

    def abc_for_share(s: float) -> ABCClass:
        if s <= 0.80:
            return "A"
        if s <= 0.95:
            return "B"
        return "C"

    out: list[AbcXyzAssignment] = []
    for sku, row in sorted_skus.iterrows():
        abc = abc_for_share(row["revenue_share_cum"])
        cv = float(row["cv_demand"])
        if cv < XYZ_LOW_CV:
            xyz: XYZClass = "X"
        elif cv < XYZ_HIGH_CV:
            xyz = "Y"
        else:
            xyz = "Z"
        out.append(AbcXyzAssignment(
            sku_id=str(sku),
            abc=abc,
            xyz=xyz,
            revenue_annual=float(row["revenue_annual"]),
            cv_demand=cv,
            revenue_share=float(row["revenue_share"]),
        ))
    return out


def heatmap_counts(assignments: list[AbcXyzAssignment]) -> dict[str, int]:
    """Return AX/AY/AZ/BX/.../CZ counts."""
    counts: dict[str, int] = {f"{a}{x}": 0 for a in "ABC" for x in "XYZ"}
    for a in assignments:
        counts[f"{a.abc}{a.xyz}"] += 1
    return counts
