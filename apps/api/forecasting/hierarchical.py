"""Hierarchical forecast reconciliation via MinT (minimum-trace).

When the panel has a `category` column, we can fit forecasts at three levels:
  Total ⊃ Category ⊃ SKU
and reconcile so that aggregating up still equals the higher-level forecast — eliminates
the noise in low-level forecasts and improves CRPS when the category structure is real.

We use Nixtla's `hierarchicalforecast.HierarchicalReconciliation` with the MinT-shrink
approach, which is the recommended robust default.

This module exposes:
- `is_available()` — True iff hierarchicalforecast imported cleanly
- `reconcile_panel(panel, base_forecasts_df)` — given a panel with category column and
  per-SKU base forecasts, return a reconciled forecast frame.

Day 11 v1: scoped to 2-level (SKU + category-total) when only category is present.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def is_available() -> bool:
    try:
        import hierarchicalforecast  # noqa: F401
        return True
    except Exception:
        return False


def build_hierarchy(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Construct the (S_df, tags) inputs HierarchicalForecast wants.

    Returns:
        Y_df (long-format aggregated history),
        S_df (summing matrix as a DataFrame: bottom-level cols, levels-as-rows),
        tags (level → list of unique_ids).
    """
    panel = panel.copy()
    panel["category"] = panel["category"].fillna("UNKNOWN").astype(str)
    panel["unique_id"] = panel["category"] + "/" + panel["sku_id"].astype(str)

    bottom = panel[["unique_id", "date", "demand"]].rename(columns={"date": "ds", "demand": "y"})
    bottom_ids = sorted(bottom["unique_id"].unique())
    cat_ids = sorted(panel["category"].unique())
    all_ids = ["TOTAL"] + cat_ids + bottom_ids

    cat_history = panel.groupby(["category", "date"], as_index=False)["demand"].sum()
    cat_history["unique_id"] = cat_history["category"]
    cat_history = cat_history[["unique_id", "date", "demand"]].rename(columns={"date": "ds", "demand": "y"})

    total_history = panel.groupby("date", as_index=False)["demand"].sum()
    total_history["unique_id"] = "TOTAL"
    total_history = total_history[["unique_id", "ds", "y"]] if "ds" in total_history.columns else total_history.rename(columns={"date": "ds", "demand": "y"})[["unique_id", "ds", "y"]]

    Y_df = pd.concat([total_history, cat_history, bottom], ignore_index=True)
    Y_df["ds"] = pd.to_datetime(Y_df["ds"])

    n_bottom = len(bottom_ids)
    S_arrays = []
    S_arrays.append(np.ones(n_bottom))  # TOTAL row
    for cat in cat_ids:
        S_arrays.append(np.array([1.0 if bid.startswith(f"{cat}/") else 0.0 for bid in bottom_ids]))
    for bid in bottom_ids:
        S_arrays.append(np.array([1.0 if other == bid else 0.0 for other in bottom_ids]))
    S_df = pd.DataFrame(np.vstack(S_arrays), index=all_ids, columns=bottom_ids)

    tags = {
        "Total": ["TOTAL"],
        "Total/Category": cat_ids,
        "Total/Category/SKU": bottom_ids,
    }
    return Y_df, S_df, tags


def reconcile_forecasts(
    Y_df: pd.DataFrame,
    Y_hat_df: pd.DataFrame,
    S_df: pd.DataFrame,
    tags: dict,
) -> pd.DataFrame:
    """Apply MinT-shrink reconciliation. Returns the same frame with an extra reconciled column."""
    from hierarchicalforecast.core import HierarchicalReconciliation
    from hierarchicalforecast.methods import MinTrace

    hrec = HierarchicalReconciliation(reconcilers=[MinTrace(method="mint_shrink")])
    return hrec.reconcile(Y_hat_df=Y_hat_df, Y_df=Y_df, S=S_df, tags=tags)
