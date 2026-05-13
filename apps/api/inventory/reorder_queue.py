"""Reorder queue scoring — ranks SKUs by stockout-prob × revenue-at-risk.

Uses an analytical approximation (no per-SKU forecast call) so we can score
hundreds of SKUs in well under a second. The recommended quantity respects
each supplier's MOQ + case-pack from the `suppliers` table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import duckdb
import pandas as pd
from scipy.stats import norm

from apps.api.db import open_dataset
from apps.api.ingestion.validators import infer_frequency
from apps.api.inventory.abc_xyz import classify_abc_xyz
from apps.api.inventory.distributions import fit_lead_time_gamma
from apps.api.inventory.supplier_metrics import _supplier_id_from_name

FREQ_TO_DAYS = {"D": 1.0, "W": 7.0, "M": 30.0}
FREQ_TO_ANNUALIZATION = {"D": 365.0, "W": 52.0, "M": 12.0}


@dataclass
class ReorderQueueItem:
    sku_id: str
    category: str | None
    supplier_name: str | None
    supplier_id: str | None
    on_hand: float | None
    reorder_point: float | None
    recommended_qty: float
    recommended_qty_raw: float
    unit_cost: float | None
    total_cost: float
    projected_stockout_date: str | None
    days_of_cover: float | None
    stockout_prob: float
    revenue_at_risk: float
    score: float
    expedite_flag: bool
    expedite_breakeven: float | None
    joint_replen_group: str | None
    moq: float | None
    case_pack: float | None
    abc_class: str
    xyz_class: str


def _round_to_moq_pack(raw_qty: float, moq: float | None, case_pack: float | None) -> float:
    qty = max(0.0, raw_qty)
    if qty <= 0:
        return 0.0
    if case_pack and case_pack > 0:
        qty = math.ceil(qty / case_pack) * case_pack
    if moq and qty > 0 and qty < moq:
        qty = moq
    return float(qty)


def _stockout_date(on_hand: float, mean_demand_per_day: float, today: date) -> str | None:
    if on_hand <= 0:
        return today.isoformat()
    if mean_demand_per_day <= 0:
        return None
    days_until = on_hand / mean_demand_per_day
    if days_until > 365:
        return None
    return (today + timedelta(days=int(days_until))).isoformat()


def compute_reorder_queue(
    dataset_id: str,
    limit: int = 200,
    days_of_cover_threshold: float = 30.0,
) -> list[ReorderQueueItem]:
    """Compute the reorder queue for a dataset. Returns SKUs sorted by score desc."""
    today = date.today()
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel ORDER BY sku_id, date").fetchdf()
        suppliers_df = conn.execute("SELECT * FROM suppliers").fetchdf()

    if panel.empty:
        return []

    sku_to_joint: dict[str, str] = {}

    by_sup = {row["name"]: row for _, row in suppliers_df.iterrows()} if not suppliers_df.empty else {}

    frequency = infer_frequency(panel["date"]) or "W"
    period_days = FREQ_TO_DAYS[frequency]
    annualization = FREQ_TO_ANNUALIZATION[frequency]

    abc_xyz_lookup = {a.sku_id: a for a in classify_abc_xyz(panel, annualization_factor=annualization)}

    items: list[ReorderQueueItem] = []
    for sku_id, sub in panel.groupby("sku_id"):
        sub = sub.sort_values("date")
        if len(sub) < 4:
            continue
        recent = sub.tail(min(13, len(sub)))
        mean_d = float(recent["demand"].mean())
        std_d = float(recent["demand"].std(ddof=0))
        if std_d == 0:
            std_d = max(0.5, mean_d * 0.1)
        unit_cost_series = sub["unit_cost"].dropna()
        unit_price_series = sub["unit_price"].dropna()
        unit_cost = float(unit_cost_series.iloc[-1]) if not unit_cost_series.empty else 1.0
        unit_price = float(unit_price_series.iloc[-1]) if not unit_price_series.empty else unit_cost * 1.5

        on_hand_series = sub["on_hand"].dropna()
        on_hand = float(on_hand_series.iloc[-1]) if not on_hand_series.empty else None

        sup_name = sub["supplier"].iloc[-1] if "supplier" in sub.columns and pd.notna(sub["supplier"].iloc[-1]) else None
        sup_meta = by_sup.get(sup_name) if sup_name else None
        moq = float(sup_meta["moq"]) if sup_meta is not None and pd.notna(sup_meta["moq"]) else None
        case_pack = float(sup_meta["case_pack"]) if sup_meta is not None and pd.notna(sup_meta["case_pack"]) else None
        supplier_id = str(sup_meta["supplier_id"]) if sup_meta is not None else (
            _supplier_id_from_name(sup_name) if sup_name else None
        )

        lt_obs = sub["lead_time_days"].dropna() if "lead_time_days" in sub.columns else pd.Series(dtype=float)
        if not lt_obs.empty:
            lt_mean = float(lt_obs.mean())
            lt_std = float(lt_obs.std(ddof=0)) if len(lt_obs) > 1 else max(lt_mean * 0.2, 0.5)
        elif sup_meta is not None and pd.notna(sup_meta["default_lead_time_days"]):
            lt_mean = float(sup_meta["default_lead_time_days"])
            lt_std = float(sup_meta["lead_time_std_days"]) if pd.notna(sup_meta["lead_time_std_days"]) else max(lt_mean * 0.2, 0.5)
        else:
            lt_mean = 14.0
            lt_std = 2.8

        lt_periods = max(1.0, lt_mean / period_days)
        ltd_mean = lt_periods * mean_d
        ltd_var = lt_periods * std_d * std_d + (mean_d * mean_d) * (lt_std / period_days) ** 2
        ltd_std = math.sqrt(max(ltd_var, 1e-9))

        if on_hand is None:
            stockout_prob = 0.0
            days_cover = None
            stockout_date = None
        else:
            z = (on_hand - ltd_mean) / max(ltd_std, 1e-6)
            stockout_prob = float(1.0 - norm.cdf(z))
            mean_d_daily = mean_d / period_days
            days_cover = float(on_hand / mean_d_daily) if mean_d_daily > 0 else None
            stockout_date = _stockout_date(on_hand, mean_d_daily, today)

        if days_cover is not None and days_cover > days_of_cover_threshold:
            continue
        if on_hand is None:
            continue

        target = ltd_mean + 1.65 * ltd_std
        raw_qty = max(0.0, target - on_hand)
        rec_qty = _round_to_moq_pack(raw_qty, moq, case_pack)
        if rec_qty <= 0:
            continue

        revenue_at_risk = float(stockout_prob * mean_d * unit_price * lt_periods)
        score = stockout_prob * revenue_at_risk

        expedite_breakeven = unit_cost * 0.5 if unit_cost > 0 else None
        expedite_flag = stockout_prob > 0.3 and revenue_at_risk > (rec_qty * (expedite_breakeven or 0))

        abc_xyz = abc_xyz_lookup.get(sku_id)
        items.append(ReorderQueueItem(
            sku_id=sku_id,
            category=sub["category"].iloc[-1] if "category" in sub.columns and pd.notna(sub["category"].iloc[-1]) else None,
            supplier_name=sup_name,
            supplier_id=supplier_id,
            on_hand=on_hand,
            reorder_point=float(ltd_mean + norm.ppf(0.95) * ltd_std),
            recommended_qty=rec_qty,
            recommended_qty_raw=float(raw_qty),
            unit_cost=unit_cost,
            total_cost=float(rec_qty * unit_cost),
            projected_stockout_date=stockout_date,
            days_of_cover=days_cover,
            stockout_prob=float(stockout_prob),
            revenue_at_risk=revenue_at_risk,
            score=float(score),
            expedite_flag=expedite_flag,
            expedite_breakeven=expedite_breakeven,
            joint_replen_group=sku_to_joint.get(sku_id),
            moq=moq,
            case_pack=case_pack,
            abc_class=abc_xyz.abc if abc_xyz else "C",
            xyz_class=abc_xyz.xyz if abc_xyz else "Z",
        ))

    items.sort(key=lambda i: i.score, reverse=True)
    return items[:limit]
