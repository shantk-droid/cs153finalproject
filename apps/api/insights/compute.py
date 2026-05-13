"""Compute the proactive insights tile.

Produces 3-5 short, actionable insights based on cheap heuristics that don't
require running forecasts. Each insight has a severity (info/warn/crit), title,
body, and optional CTA.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import norm

from apps.api.db import open_dataset
from apps.api.ingestion.validators import infer_frequency

FREQ_TO_DAYS = {"D": 1.0, "W": 7.0, "M": 30.0}
Severity = Literal["info", "warn", "crit"]


def _abc_class_from_revenue(rev_series: pd.Series) -> dict[str, str]:
    """Pareto on revenue: A = top 80% cumulative, B = next 15%, C = rest."""
    if rev_series.empty:
        return {}
    sorted_rev = rev_series.sort_values(ascending=False)
    cumsum = sorted_rev.cumsum()
    total = sorted_rev.sum()
    if total <= 0:
        return {sku: "C" for sku in rev_series.index}
    pct = cumsum / total
    out: dict[str, str] = {}
    for sku, p in pct.items():
        if p <= 0.80:
            out[sku] = "A"
        elif p <= 0.95:
            out[sku] = "B"
        else:
            out[sku] = "C"
    return out


def compute_insights(dataset_id: str) -> list[dict]:
    insights: list[dict] = []
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel ORDER BY date").fetchdf()
        suppliers_df = conn.execute("SELECT * FROM suppliers").fetchdf()
        receipts_df = conn.execute("SELECT * FROM receipts").fetchdf()

    if panel.empty:
        return insights

    frequency = infer_frequency(panel["date"]) or "W"
    period_days = FREQ_TO_DAYS[frequency]
    base = f"/dashboard/{dataset_id}"

    last_date = panel["date"].max()
    cutoff_recent = last_date - pd.Timedelta(days=90)
    cutoff_prior = last_date - pd.Timedelta(days=180)
    recent = panel[panel["date"] > cutoff_recent]
    prior = panel[(panel["date"] > cutoff_prior) & (panel["date"] <= cutoff_recent)]

    if not recent.empty and not prior.empty:
        recent_rev = recent.assign(rev=recent["demand"] * recent["unit_price"].fillna(0)).groupby("sku_id")["rev"].sum()
        prior_rev = prior.assign(rev=prior["demand"] * prior["unit_price"].fillna(0)).groupby("sku_id")["rev"].sum()
        abc_recent = _abc_class_from_revenue(recent_rev)
        abc_prior = _abc_class_from_revenue(prior_rev)
        moves: list[tuple[str, str, str]] = []
        for sku in set(abc_recent) & set(abc_prior):
            if abc_recent[sku] != abc_prior[sku]:
                moves.append((sku, abc_prior[sku], abc_recent[sku]))
        upgrades = [m for m in moves if "ABC".index(m[2]) < "ABC".index(m[1])]
        if upgrades:
            insights.append({
                "id": "abc_upgrades",
                "severity": "info",
                "title": f"{len(upgrades)} SKUs migrated to higher class",
                "body": ", ".join(f"{m[0]} ({m[1]}→{m[2]})" for m in upgrades[:3]) + (
                    f" + {len(upgrades) - 3} more" if len(upgrades) > 3 else ""
                ),
                "cta_label": "See SKUs",
                "cta_href": f"{base}/forecasts",
            })

    last_per_sku = panel.sort_values("date").groupby("sku_id").tail(1)
    recent_panel = panel[panel["date"] > cutoff_recent]
    mean_d = recent_panel.groupby("sku_id")["demand"].mean()
    low_cover_skus = []
    for _, row in last_per_sku.iterrows():
        sku = row["sku_id"]
        if pd.isna(row["on_hand"]):
            continue
        md = mean_d.get(sku, 0.0)
        if md <= 0:
            continue
        days_cover = float(row["on_hand"]) / md * period_days
        if days_cover < 7:
            low_cover_skus.append((sku, days_cover))
    if low_cover_skus:
        low_cover_skus.sort(key=lambda x: x[1])
        insights.append({
            "id": "low_cover",
            "severity": "crit",
            "title": f"{len(low_cover_skus)} SKUs have <7 days of cover",
            "body": "Top: " + ", ".join(f"{s} ({d:.1f}d)" for s, d in low_cover_skus[:3]),
            "cta_label": "Reorder queue",
            "cta_href": f"{base}/reorder",
        })

    if not receipts_df.empty:
        recent_rcp = receipts_df[pd.to_datetime(receipts_df["received_date"]) > (last_date - pd.Timedelta(days=120))]
        otif_by_sup: list[tuple[str, float, int]] = []
        for sup_id, group in recent_rcp.groupby("supplier_id"):
            if len(group) < 3:
                continue
            on_time = (pd.to_datetime(group["received_date"]) <= pd.to_datetime(group["expected_date"])).mean()
            in_full = (group["received_qty"] >= group["ordered_qty"] * 0.99).mean()
            otif = float(on_time * in_full * 100)
            otif_by_sup.append((sup_id, otif, len(group)))
        otif_by_sup.sort(key=lambda x: x[1])
        bad = [t for t in otif_by_sup if t[1] < 75]
        if bad:
            sup_id_to_name = {row["supplier_id"]: row["name"] for _, row in suppliers_df.iterrows()}
            sup_id, otif, n = bad[0]
            insights.append({
                "id": f"otif_{sup_id}",
                "severity": "warn",
                "title": f"{sup_id_to_name.get(sup_id, sup_id)} OTIF dropped to {otif:.0f}%",
                "body": f"{n} recent receipts. Consider dual-sourcing or expediting key SKUs.",
                "cta_label": "Open scorecard",
                "cta_href": f"{base}/suppliers/{sup_id}",
            })

    expedite_count = 0
    for _, row in last_per_sku.iterrows():
        sku = row["sku_id"]
        if pd.isna(row["on_hand"]):
            continue
        md = mean_d.get(sku, 0.0)
        if md <= 0:
            continue
        days_cover = float(row["on_hand"]) / md * period_days
        unit_price = float(row.get("unit_price", 0)) if pd.notna(row.get("unit_price")) else 0
        if days_cover < 14 and md * unit_price > 50:
            expedite_count += 1
    if expedite_count > 0:
        insights.append({
            "id": "expedite_candidates",
            "severity": "warn" if expedite_count < 5 else "crit",
            "title": f"{expedite_count} SKUs flagged for expediting",
            "body": "Air-freight breakeven beats stockout cost on these high-revenue SKUs.",
            "cta_label": "Review queue",
            "cta_href": f"{base}/reorder",
        })

    if not panel.empty and len(panel) > 0:
        n_skus = panel["sku_id"].nunique()
        n_days = (panel["date"].max() - panel["date"].min()).days
        insights.append({
            "id": "data_summary",
            "severity": "info",
            "title": f"{n_skus} SKUs · {n_days // 30}+ months of history",
            "body": f"Latest data: {pd.Timestamp(panel['date'].max()).date().isoformat()}. {len(panel):,} observations.",
            "cta_label": None,
            "cta_href": None,
        })

    return insights
