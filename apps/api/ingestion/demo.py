"""Demo dataset bootstrapping.

Creates a fully-loaded dataset (panel + suppliers + receipts) directly from
the synthetic generator. Bypasses the upload/confirm flow so the live demo
works without shipping CSVs in the container.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd

from apps.api.assertions.schemas import DataQualityReport
from apps.api.assertions.score import compute_dq_report
from apps.api.assertions.statistical import panel_metric_medians
from apps.api.config import get_settings
from apps.api.db import dataset_path, ensure_all_tables, open_dataset
from apps.api.ingestion.schemas import DatasetSummary
from apps.api.ingestion.storage import DatasetMetadata, write_dataset_metadata
from apps.api.ingestion.validators import infer_frequency
from apps.api.profiles import match_profile
from apps.api.synthetic import TEMPLATES, generate_template_full

# Demo template → reference profile. Used so demo datasets land in their natural
# profile (instead of running auto-detect from scratch every boot).
TEMPLATE_PROFILE: dict[str, str] = {
    "retail_stable": "retail_m5",
    "coffee_perishable": "retail_m5",
    "ecommerce_lumpy": "ecommerce_fashion",
    "pharma_steady": "pharma_medical",
    "spare_parts_mro": "spare_parts_mro",
    "b2b_industrial": "b2b_industrial",
}


def list_templates() -> list[dict]:
    """Return the list of available demo templates with descriptive metadata."""
    descriptions = {
        "retail_stable": "Stable weekly retail SKUs — beverages, snacks, household. 200 SKUs × 2 yrs.",
        "coffee_perishable": "Daily coffee shop demand — short lead times, seasonal peaks. 80 SKUs × 6 mo.",
        "ecommerce_lumpy": "Long-tail e-commerce — intermittent, lumpy demand. 300 SKUs × 2 yrs.",
        "b2b_industrial": "B2B distributor — lumpy orders, weak seasonality, stable trend. 150 SKUs × 2 yrs.",
        "pharma_steady": "Pharma / medical — stable chronic-meds demand, mild flu/allergy seasonality. 120 SKUs × 2 yrs.",
        "spare_parts_mro": "Spare parts / MRO — extreme intermittent service demand. 180 SKUs × 2 yrs.",
    }
    out = []
    for name in TEMPLATES:
        kw = TEMPLATES[name].kwargs
        out.append({
            "name": name,
            "description": descriptions.get(name, ""),
            "n_skus": kw["n_skus"],
            "n_periods": kw["n_periods"],
            "frequency": kw["frequency"],
        })
    return out


def create_demo_dataset(template: str, seed: int = 42) -> tuple[str, DatasetSummary]:
    """Create a new dataset bootstrapped from a synthetic template. Returns (dataset_id, summary)."""
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template!r}; known: {list(TEMPLATES)}")

    panel, suppliers, receipts = generate_template_full(template, seed=seed)

    dataset_id = str(uuid.uuid4())
    settings = get_settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)

    db_file = dataset_path(dataset_id)
    if db_file.exists():
        db_file.unlink()

    panel_for_db = panel.copy()
    panel_for_db["date"] = pd.to_datetime(panel_for_db["date"]).dt.date

    with open_dataset(dataset_id) as conn:
        ensure_all_tables(conn)
        conn.register("panel_in", panel_for_db)
        conn.execute("INSERT INTO panel SELECT * FROM panel_in")
        conn.unregister("panel_in")
        conn.register("suppliers_in", suppliers)
        conn.execute("INSERT INTO suppliers SELECT * FROM suppliers_in")
        conn.unregister("suppliers_in")
        receipts_for_db = receipts.copy()
        for col in ("ordered_date", "expected_date", "received_date"):
            receipts_for_db[col] = pd.to_datetime(receipts_for_db[col]).dt.date
        conn.register("receipts_in", receipts_for_db)
        conn.execute("INSERT INTO receipts SELECT * FROM receipts_in")
        conn.unregister("receipts_in")

    canonical = panel.copy()
    canonical["date"] = pd.to_datetime(canonical["date"])
    profile_id = TEMPLATE_PROFILE.get(template, "retail_m5")
    write_dataset_metadata(DatasetMetadata(
        dataset_id=dataset_id,
        profile_id=profile_id,
        profile_auto_detected=False,
    ))
    report = compute_dq_report(
        dataset_id,
        canonical,
        profile_id=profile_id,
        schema_assertions=[],
    )
    reports_dir = settings.data_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{dataset_id}.json").write_text(report.model_dump_json(indent=2))

    summary = DatasetSummary(
        dataset_id=dataset_id,
        n_rows=len(canonical),
        n_skus=int(canonical["sku_id"].nunique()),
        date_min=canonical["date"].min().date(),
        date_max=canonical["date"].max().date(),
        frequency=infer_frequency(canonical["date"]),  # type: ignore[arg-type]
        n_categories=int(canonical["category"].nunique()) if "category" in canonical.columns else 0,
        n_suppliers=int(canonical["supplier"].nunique()) if "supplier" in canonical.columns else 0,
        has_on_hand="on_hand" in canonical.columns and canonical["on_hand"].notna().any(),
        has_lead_time="lead_time_days" in canonical.columns and canonical["lead_time_days"].notna().any(),
        has_unit_cost="unit_cost" in canonical.columns and canonical["unit_cost"].notna().any(),
        has_unit_price="unit_price" in canonical.columns and canonical["unit_price"].notna().any(),
    )
    return dataset_id, summary
