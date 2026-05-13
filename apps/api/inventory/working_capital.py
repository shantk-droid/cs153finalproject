"""Working capital + cash-to-cash cycle metrics.

DIO = (inventory $ / annual COGS) × 365
DPO = weighted avg of supplier payment terms (Net 30 etc.) × payable share
DSO = 0 (we don't have AR data; documented as an assumption)
Cash-to-cash = DIO + DSO − DPO
"""

from __future__ import annotations

import pandas as pd

from apps.api.db import open_dataset
from apps.api.ingestion.validators import infer_frequency
from apps.api.inventory.supplier_metrics import parse_payment_terms_days


FREQ_ANNUALIZATION = {"D": 365, "W": 52, "M": 12}


def compute_working_capital(dataset_id: str) -> dict:
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel").fetchdf()
        suppliers_df = conn.execute("SELECT * FROM suppliers").fetchdf()

    if panel.empty:
        return {
            "inventory_value": 0.0, "annual_cogs": 0.0,
            "dio_days": None, "dpo_days": None, "cash_to_cash_days": None,
            "payable_outstanding": 0.0, "by_supplier": [],
        }

    frequency = infer_frequency(panel["date"]) or "W"
    annualization = FREQ_ANNUALIZATION[frequency]

    last_per_sku = panel.sort_values("date").groupby("sku_id").tail(1)
    inventory_value = 0.0
    if "on_hand" in last_per_sku.columns and "unit_cost" in last_per_sku.columns:
        oh = last_per_sku["on_hand"].fillna(0)
        uc = last_per_sku["unit_cost"].fillna(0)
        inventory_value = float((oh * uc).sum())

    annual_cogs = 0.0
    if "unit_cost" in panel.columns:
        annual_cogs = float((panel["demand"] * panel["unit_cost"].fillna(0)).sum() * annualization / max(1, panel["date"].nunique()))
    if annual_cogs <= 0 and inventory_value > 0:
        annual_cogs = inventory_value * 4

    dio_days: float | None = None
    if annual_cogs > 0:
        dio_days = round(inventory_value / annual_cogs * 365, 1)

    by_supplier: list[dict] = []
    payable_outstanding_total = 0.0
    weighted_terms_sum = 0.0
    weight_sum = 0.0
    sup_to_terms_days: dict[str, int] = {}
    sup_to_id: dict[str, str] = {}
    if not suppliers_df.empty:
        for _, sup in suppliers_df.iterrows():
            terms_days = parse_payment_terms_days(sup["payment_terms"])
            sup_to_terms_days[sup["name"]] = terms_days
            sup_to_id[sup["name"]] = sup["supplier_id"]

    if "supplier" in panel.columns:
        for sup_name, sub in last_per_sku.groupby("supplier"):
            if sup_name is None or pd.isna(sup_name):
                continue
            sub_value = float((sub["on_hand"].fillna(0) * sub["unit_cost"].fillna(0)).sum()) if "on_hand" in sub.columns else 0.0
            terms = sup_to_terms_days.get(sup_name, 30)
            payable = sub_value * (terms / 30.0) * (1 / 12)
            payable_outstanding_total += payable
            weighted_terms_sum += terms * sub_value
            weight_sum += sub_value
            by_supplier.append({
                "supplier_id": sup_to_id.get(sup_name, sup_name),
                "supplier_name": sup_name,
                "inventory_value": round(sub_value, 2),
                "payment_terms_days": terms,
                "payable_outstanding": round(payable, 2),
            })

    dpo_days: float | None = None
    if weight_sum > 0:
        dpo_days = round(weighted_terms_sum / weight_sum, 1)

    cash_to_cash: float | None = None
    if dio_days is not None and dpo_days is not None:
        cash_to_cash = round(dio_days + 0 - dpo_days, 1)

    by_supplier.sort(key=lambda x: x["inventory_value"], reverse=True)

    return {
        "inventory_value": round(inventory_value, 2),
        "annual_cogs": round(annual_cogs, 2),
        "dio_days": dio_days,
        "dpo_days": dpo_days,
        "cash_to_cash_days": cash_to_cash,
        "payable_outstanding": round(payable_outstanding_total, 2),
        "by_supplier": by_supplier[:20],
    }
