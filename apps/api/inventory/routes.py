"""FastAPI router for inventory endpoints: /skus listing, /skus/{id}/recommend, aggregate_stats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from apps.api.assertions.schemas import DataQualityReport
from apps.api.config import get_settings
from apps.api.db import dataset_path, open_dataset
from apps.api.ingestion.validators import infer_frequency
from apps.api.inventory.abc_xyz import classify_abc_xyz, heatmap_counts
from apps.api.inventory.recommend import recommend_sku
from apps.api.inventory.schemas import (
    AggregateStats,
    Recommendation,
    RecommendationOverrides,
    SkuTableRow,
)
from apps.api.inventory.status import derive_status

router = APIRouter(prefix="/datasets", tags=["inventory"])


@router.post(
    "/{dataset_id}/skus/{sku_id}/recommend",
    response_model=Recommendation,
)
async def post_recommend(
    dataset_id: str,
    sku_id: str,
    overrides: RecommendationOverrides | None = None,
) -> Recommendation:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    try:
        return recommend_sku(dataset_id, sku_id, overrides=overrides or RecommendationOverrides())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class ScenarioResponse(BaseModel):
    base: Recommendation
    scenario: Recommendation
    deltas: dict[str, float]


@router.post(
    "/{dataset_id}/skus/{sku_id}/scenario",
    response_model=ScenarioResponse,
)
async def post_scenario(
    dataset_id: str,
    sku_id: str,
    overrides: RecommendationOverrides | None = None,
) -> ScenarioResponse:
    """Compute base (no overrides) vs scenario (with overrides) recommendation in one shot,
    plus a small `deltas` dict so the UI can highlight the diff without recomputing on the client.
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    overrides = overrides or RecommendationOverrides()
    try:
        base = recommend_sku(dataset_id, sku_id, overrides=RecommendationOverrides())
        scenario = recommend_sku(dataset_id, sku_id, overrides=overrides)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    deltas = {
        "safety_stock":                 scenario.safety_stock - base.safety_stock,
        "expected_stockout_prob":       scenario.expected_stockout_prob - base.expected_stockout_prob,
        "expected_fill_rate":           scenario.expected_fill_rate - base.expected_fill_rate,
        "expected_holding_cost_annual": scenario.expected_holding_cost_annual - base.expected_holding_cost_annual,
        "expected_total_cost_annual":   scenario.expected_total_cost_annual - base.expected_total_cost_annual,
        "recommended_order_qty":        scenario.recommended_order_qty - base.recommended_order_qty,
    }
    return ScenarioResponse(base=base, scenario=scenario, deltas=deltas)


@router.get("/{dataset_id}/skus", response_model=list[SkuTableRow])
async def list_skus(
    dataset_id: str,
    limit: int = Query(default=200, ge=1, le=10_000),
    offset: int = Query(default=0, ge=0),
    category: str | None = None,
    supplier: str | None = None,
    abc: Literal["A", "B", "C"] | None = None,
    xyz: Literal["X", "Y", "Z"] | None = None,
    sort_by: Literal["sku_id", "revenue_annual", "cv_demand", "last_demand", "days_of_cover", "status"] = "days_of_cover",
    sort_dir: Literal["asc", "desc"] = "asc",
    status: Literal["order_now", "at_risk", "watch", "healthy"] | None = None,
    include_history: bool = Query(default=False),
    history_periods: int = Query(default=12, ge=1, le=104),
) -> list[SkuTableRow]:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel").fetchdf()
    if panel.empty:
        return []

    frequency = infer_frequency(panel["date"]) or "W"
    annualization = {"D": 365, "W": 52, "M": 12}[frequency]
    assignments = {a.sku_id: a for a in classify_abc_xyz(panel, annualization_factor=annualization)}

    last_per_sku = panel.sort_values("date").groupby("sku_id").tail(1).set_index("sku_id")
    n_obs_per_sku = panel.groupby("sku_id").size()
    mean_recent_demand = panel.groupby("sku_id").apply(lambda g: g.tail(8)["demand"].mean(), include_groups=False)

    history_per_sku: dict[str, list[float]] = {}
    if include_history:
        for sku, sub in panel.sort_values("date").groupby("sku_id"):
            tail = sub.tail(history_periods)["demand"].astype(float).tolist()
            history_per_sku[sku] = tail

    rows: list[SkuTableRow] = []
    for sku_id_, last_row in last_per_sku.iterrows():
        a = assignments.get(sku_id_)
        if not a:
            continue
        if category and last_row.get("category") != category:
            continue
        if supplier and last_row.get("supplier") != supplier:
            continue
        if abc and a.abc != abc:
            continue
        if xyz and a.xyz != xyz:
            continue

        on_hand = last_row.get("on_hand")
        on_hand_val = float(on_hand) if on_hand is not None and not pd.isna(on_hand) else None
        recent_demand = float(mean_recent_demand.get(sku_id_, 0.0))
        days_of_cover: float | None = None
        if on_hand_val is not None and recent_demand > 0:
            period_days = {"D": 1.0, "W": 7.0, "M": 30.0}[frequency]
            days_of_cover = round(on_hand_val / recent_demand * period_days, 1)
        lt_raw = last_row.get("lead_time_days")
        lead_time_val = float(lt_raw) if lt_raw is not None and not pd.isna(lt_raw) else None
        sku_status = derive_status(on_hand_val, days_of_cover, lead_time_val)

        if status and sku_status != status:
            continue

        rows.append(SkuTableRow(
            sku_id=str(sku_id_),
            category=last_row.get("category"),
            supplier=last_row.get("supplier"),
            abc_class=a.abc,
            xyz_class=a.xyz,
            last_demand=float(last_row["demand"]) if not pd.isna(last_row["demand"]) else 0.0,
            on_hand=on_hand_val,
            days_of_cover=days_of_cover,
            cv_demand=round(a.cv_demand, 3),
            revenue_annual=round(a.revenue_annual, 2),
            n_obs=int(n_obs_per_sku.get(sku_id_, 0)),
            history=history_per_sku.get(sku_id_) if include_history else None,
            lead_time_days=lead_time_val,
            status=sku_status,
        ))

    _STATUS_ORDER = {"order_now": 0, "at_risk": 1, "watch": 2, "healthy": 3}
    sort_key = {
        "sku_id":         lambda r: r.sku_id,
        "revenue_annual": lambda r: r.revenue_annual,
        "cv_demand":      lambda r: r.cv_demand,
        "last_demand":    lambda r: r.last_demand,
        "days_of_cover":  lambda r: (r.days_of_cover if r.days_of_cover is not None else float("inf")),
        "status":         lambda r: _STATUS_ORDER[r.status],
    }[sort_by]
    rows.sort(key=sort_key, reverse=(sort_dir == "desc"))
    return rows[offset:offset + limit]


@router.post("/{dataset_id}/reconcile")
async def post_reconcile(dataset_id: str, horizon: int = Query(default=12, ge=1, le=52)) -> dict:
    """Run hierarchical (MinT-shrink) reconciliation across all SKUs grouped by category.

    This is the batch endpoint — for a dataset with N SKUs and a `category` column, it
    forecasts each SKU + each category-total + the dataset total, then reconciles so the
    SKU forecasts sum to the category forecast and categories sum to the total. Returns
    summary statistics (we don't ship N×horizon back; the per-SKU reconciled quantiles are
    cached on disk and consumed by /skus/{id}/forecast on subsequent calls).
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.forecasting import hierarchical
    from apps.api.forecasting.classical import forecast_classical, history_dataframe
    from apps.api.forecasting.characterize import characterize_with_classifier
    from apps.api.ingestion.validators import infer_frequency

    if not hierarchical.is_available():
        raise HTTPException(status_code=503, detail="hierarchicalforecast not installed")

    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT sku_id, date, demand, category FROM panel").fetchdf()
    if panel.empty or panel["category"].isna().all():
        raise HTTPException(status_code=422, detail="no category column — hierarchical reconciliation requires it")

    frequency = infer_frequency(panel["date"]) or "W"
    panel = panel.dropna(subset=["category"]).copy()

    Y_df, S_df, tags = hierarchical.build_hierarchy(panel)

    base_rows: list[pd.DataFrame] = []
    for unique_id, g in Y_df.groupby("unique_id"):
        if len(g) < 8:
            continue
        try:
            pattern, _ = characterize_with_classifier(g["y"], frequency)
        except Exception:
            pattern = "smooth"
        history = history_dataframe(unique_id, g["ds"], g["y"])
        try:
            out = forecast_classical(history, horizon, frequency, pattern)
        except Exception:
            continue
        future_dates = pd.date_range(start=g["ds"].max(), periods=horizon + 1, freq={"D": "D", "W": "W-MON", "M": "MS"}[frequency])[1:]
        df_fc = pd.DataFrame({
            "unique_id": unique_id,
            "ds": future_dates,
            "AutoModel": out.point,
        })
        base_rows.append(df_fc)
    if not base_rows:
        raise HTTPException(status_code=500, detail="no base forecasts produced")
    Y_hat_df = pd.concat(base_rows, ignore_index=True)

    try:
        reconciled = hierarchical.reconcile_forecasts(Y_df=Y_df, Y_hat_df=Y_hat_df, S_df=S_df, tags=tags)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"reconciliation failed: {e}") from e

    settings = get_settings()
    cache_dir = settings.data_path / "reconciled"
    cache_dir.mkdir(parents=True, exist_ok=True)
    reconciled.to_parquet(cache_dir / f"{dataset_id}.parquet", index=False)

    return {
        "dataset_id": dataset_id,
        "n_series_reconciled": int(reconciled["unique_id"].nunique()),
        "horizon_periods": horizon,
        "frequency": frequency,
        "method": "MinTrace(mint_shrink)",
        "n_levels": 3,
    }


@router.get("/{dataset_id}/skus/{sku_id}/calibration")
async def sku_calibration(dataset_id: str, sku_id: str) -> dict:
    """Per-SKU comparison to M5 reference distributions. Mirrors the chat tool, exposed for
    direct UI consumption via a CalibrationCard on /sku/[id].
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.assertions.statistical import _matched_dept_row, metrics_for_sku
    from apps.api.m5.loader import dq_reference_dists, calibration_version

    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT date, demand, category FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id.strip().upper()],
        ).fetchdf()
    if df.empty:
        raise HTTPException(status_code=404, detail=f"sku '{sku_id}' not in dataset")

    arr = df["demand"].to_numpy(dtype=float)
    category = df["category"].iloc[0] if "category" in df.columns and pd.notna(df["category"].iloc[0]) else None
    metrics = metrics_for_sku(arr)

    ref = dq_reference_dists()
    if ref is None:
        return {
            "sku_id": sku_id.strip().upper(),
            "category": category,
            "calibration_version": calibration_version(),
            "metrics": metrics, "comparisons": [],
            "note": "M5 reference distributions not available.",
        }

    comparisons = []
    for metric_name, value in metrics.items():
        ref_row = _matched_dept_row(ref, category, metric_name)
        if ref_row is None:
            continue
        position = "p25_to_p75"
        percentile_band: tuple[int, int] = (25, 75)
        if value <= ref_row["p1"]:
            position, percentile_band = "below_p1", (0, 1)
        elif value <= ref_row["p5"]:
            position, percentile_band = "p1_to_p5", (1, 5)
        elif value <= ref_row["p25"]:
            position, percentile_band = "p5_to_p25", (5, 25)
        elif value <= ref_row["p75"]:
            position, percentile_band = "p25_to_p75", (25, 75)
        elif value <= ref_row["p95"]:
            position, percentile_band = "p75_to_p95", (75, 95)
        elif value <= ref_row["p99"]:
            position, percentile_band = "p95_to_p99", (95, 99)
        else:
            position, percentile_band = "above_p99", (99, 100)
        comparisons.append({
            "metric": metric_name,
            "user_value": round(float(value), 4),
            "m5_p1": round(float(ref_row["p1"]), 4),
            "m5_p25": round(float(ref_row["p25"]), 4),
            "m5_p50": round(float(ref_row["p50"]), 4),
            "m5_p75": round(float(ref_row["p75"]), 4),
            "m5_p99": round(float(ref_row["p99"]), 4),
            "position": position,
            "percentile_band": list(percentile_band),
            "matched_dept": str(ref_row["dept_id"]),
        })

    return {
        "sku_id": sku_id.strip().upper(),
        "category": category,
        "calibration_version": calibration_version(),
        "metrics": metrics, "comparisons": comparisons,
    }


@router.get("/{dataset_id}/skus/{sku_id}/history")
async def sku_history(
    dataset_id: str,
    sku_id: str,
    last_n: int = Query(default=104, ge=1, le=2000),
) -> list[dict]:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT date, demand FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id.strip().upper()],
        ).fetchdf()
    if df.empty:
        raise HTTPException(status_code=404, detail=f"sku '{sku_id}' has no history")
    df = df.tail(last_n)
    return [
        {"date": pd.Timestamp(d).date().isoformat(), "demand": float(v)}
        for d, v in zip(df["date"], df["demand"])
    ]


@router.get("/{dataset_id}/settings")
async def get_dataset_settings_route(dataset_id: str):
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.settings import load_dataset_settings
    return load_dataset_settings(dataset_id).model_dump()


@router.put("/{dataset_id}/settings")
async def put_dataset_settings(dataset_id: str, body: dict):
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.settings import DatasetSettings, save_dataset_settings
    try:
        settings_obj = DatasetSettings.model_validate(body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    save_dataset_settings(dataset_id, settings_obj)
    return settings_obj.model_dump()


@router.get("/{dataset_id}/joint_replenishment")
async def joint_replenishment_route(dataset_id: str) -> list[dict]:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.joint_replen import recommend_joint_replenishment
    from apps.api.inventory.settings import load_dataset_settings

    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT sku_id, demand, supplier, unit_cost FROM panel").fetchdf()
        df_dates = conn.execute("SELECT DISTINCT date FROM panel ORDER BY date").fetchdf()
    frequency = infer_frequency(df_dates["date"]) or "W"
    annualization = {"D": 365, "W": 52, "M": 12}[frequency]
    persisted = load_dataset_settings(dataset_id)

    groups = recommend_joint_replenishment(
        panel=panel, annualization_factor=annualization,
        order_cost_default=persisted.order_cost,
        holding_cost_rate_default=persisted.holding_cost_rate,
    )
    return [
        {
            "supplier": g.supplier, "group_id": g.group_id,
            "cadence_days": round(g.cadence_days, 1),
            "n_members": len(g.members),
            "members": [{"sku_id": m.sku_id,
                         "individual_cycle_days": round(m.individual_cycle_days, 1),
                         "annual_demand": round(m.annual_demand, 1),
                         "eoq": round(m.eoq, 1)} for m in g.members],
            "annual_orders_pooled": round(g.annual_orders_pooled, 2),
            "annual_orders_individual": round(g.annual_orders_individual, 2),
            "annual_savings_usd": round(g.annual_savings_usd, 2),
            "note": g.note,
        }
        for g in groups
    ]


@router.get("/{dataset_id}/export")
async def export_recommendations(
    dataset_id: str,
    fmt: Literal["csv", "xlsx"] = Query(default="csv"),
    sample_skus: int | None = Query(default=None, ge=1, le=10_000),
):
    """Bulk per-SKU recommendations export. Forecasts + recommends each SKU.

    `sample_skus` caps how many SKUs to export — useful for large panels.
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from apps.api.inventory.recommend import recommend_sku

    with open_dataset(dataset_id, read_only=True) as conn:
        sku_ids = [r[0] for r in conn.execute("SELECT DISTINCT sku_id FROM panel ORDER BY sku_id").fetchall()]
    if sample_skus:
        sku_ids = sku_ids[:sample_skus]

    rows: list[dict] = []
    for sid in sku_ids:
        try:
            r = recommend_sku(dataset_id, sid, overrides=RecommendationOverrides())
        except Exception as e:
            rows.append({"sku_id": sid, "error": f"{type(e).__name__}: {e}"})
            continue
        rows.append({
            "sku_id": r.sku_id, "policy": r.policy_name,
            "abc_xyz": f"{r.abc_class}{r.xyz_class}",
            "recommended_order_qty": round(r.recommended_order_qty, 1),
            "reorder_point": "" if r.reorder_point is None else round(r.reorder_point, 1),
            "safety_stock": round(r.safety_stock, 1),
            "expected_stockout_prob": round(r.expected_stockout_prob, 4),
            "expected_fill_rate": round(r.expected_fill_rate, 4),
            "expected_total_cost_annual": round(r.expected_total_cost_annual, 2),
            "caveats": " | ".join(r.caveats),
        })

    df = pd.DataFrame(rows)
    fname_base = f"{dataset_id}-recommendations"
    if fmt == "csv":
        buf = BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            buf, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname_base}.csv"'},
        )
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="recommendations", index=False)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname_base}.xlsx"'},
    )


# ---------- Phase 2: Reorder & Purchase Orders ----------


class DraftPORequest(BaseModel):
    sku_id: str
    qty: float
    notes: str | None = None


class POPatchRequest(BaseModel):
    status: Literal["drafted", "approved", "placed", "received", "cancelled"] | None = None
    assigned_to: str | None = None
    approved_by: str | None = None
    notes: str | None = None
    by_user: str | None = None
    transition_note: str | None = None


def _po_to_dict(po) -> dict:
    return {
        "po_id": po.po_id,
        "supplier_id": po.supplier_id,
        "supplier_name": po.supplier_name,
        "status": po.status,
        "created_at": po.created_at,
        "needed_by": po.needed_by,
        "total_cost": po.total_cost,
        "total_units": po.total_units,
        "expedite_flag": po.expedite_flag,
        "joint_replen_group": po.joint_replen_group,
        "assigned_to": po.assigned_to,
        "approved_by": po.approved_by,
        "notes": po.notes,
        "lines": [
            {"po_id": l.po_id, "sku_id": l.sku_id, "qty": l.qty, "unit_cost": l.unit_cost}
            for l in po.lines
        ],
        "status_log": [
            {
                "from_status": e.from_status,
                "to_status": e.to_status,
                "by_user": e.by_user,
                "at": e.at,
                "note": e.note,
            }
            for e in po.status_log
        ],
    }


class PlanReorderWeekBody(BaseModel):
    service_level: float = 0.95
    budget_cap_usd: float | None = None
    top_n: int = 25


@router.post("/{dataset_id}/plan_reorder_week")
async def post_plan_reorder_week(
    dataset_id: str,
    body: PlanReorderWeekBody | None = None,
) -> dict:
    """Generate a one-week reorder plan: top-N urgent SKUs ranked by stockout × revenue-at-risk,
    optionally filtered by a USD budget cap (greedy by risk-per-dollar).

    Used by the chat agent (Buyer specialist + plan_reorder_week tool) and by the dashboard
    briefing card. Items that don't fit under the budget appear in `deferred_items`.
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    body = body or PlanReorderWeekBody()
    from apps.api.inventory.recommend import plan_reorder_week
    try:
        return plan_reorder_week(
            dataset_id,
            service_level=body.service_level,
            budget_cap_usd=body.budget_cap_usd,
            top_n=body.top_n,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/{dataset_id}/reorder/queue")
async def get_reorder_queue(
    dataset_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    days_threshold: float = Query(default=30.0, ge=0.0, le=365.0),
) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.reorder_queue import compute_reorder_queue
    items = compute_reorder_queue(dataset_id, limit=limit, days_of_cover_threshold=days_threshold)
    return {
        "items": [
            {
                "sku_id": i.sku_id,
                "category": i.category,
                "supplier_name": i.supplier_name,
                "supplier_id": i.supplier_id,
                "on_hand": i.on_hand,
                "reorder_point": i.reorder_point,
                "recommended_qty": i.recommended_qty,
                "recommended_qty_raw": i.recommended_qty_raw,
                "unit_cost": i.unit_cost,
                "total_cost": i.total_cost,
                "projected_stockout_date": i.projected_stockout_date,
                "days_of_cover": i.days_of_cover,
                "stockout_prob": i.stockout_prob,
                "revenue_at_risk": i.revenue_at_risk,
                "score": i.score,
                "expedite_flag": i.expedite_flag,
                "expedite_breakeven": i.expedite_breakeven,
                "joint_replen_group": i.joint_replen_group,
                "moq": i.moq,
                "case_pack": i.case_pack,
                "abc_class": i.abc_class,
                "xyz_class": i.xyz_class,
            }
            for i in items
        ],
        "generated_at": pd.Timestamp.utcnow().isoformat(),
    }


@router.post("/{dataset_id}/reorder/draft")
async def draft_purchase_order(dataset_id: str, body: DraftPORequest) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.purchase_orders import draft_purchase_order_from_sku
    try:
        po = draft_purchase_order_from_sku(dataset_id, body.sku_id, body.qty, notes=body.notes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _po_to_dict(po)


@router.get("/{dataset_id}/purchase_orders")
async def list_purchase_orders_route(
    dataset_id: str,
    status: Literal["drafted", "approved", "placed", "received", "cancelled"] | None = None,
) -> list[dict]:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.purchase_orders import list_purchase_orders
    pos = list_purchase_orders(dataset_id, status=status)
    return [_po_to_dict(po) for po in pos]


@router.get("/{dataset_id}/purchase_orders/{po_id}")
async def get_purchase_order_route(dataset_id: str, po_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.purchase_orders import get_purchase_order
    po = get_purchase_order(dataset_id, po_id)
    if po is None:
        raise HTTPException(status_code=404, detail=f"PO {po_id} not found")
    return _po_to_dict(po)


@router.patch("/{dataset_id}/purchase_orders/{po_id}")
async def patch_purchase_order(dataset_id: str, po_id: str, body: POPatchRequest) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.purchase_orders import update_purchase_order
    try:
        po = update_purchase_order(
            dataset_id,
            po_id,
            status=body.status,
            assigned_to=body.assigned_to,
            approved_by=body.approved_by,
            notes=body.notes,
            by_user=body.by_user,
            transition_note=body.transition_note,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _po_to_dict(po)


@router.delete("/{dataset_id}/purchase_orders/{po_id}")
async def delete_purchase_order_route(dataset_id: str, po_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.purchase_orders import delete_purchase_order
    delete_purchase_order(dataset_id, po_id)
    return {"deleted": po_id}


@router.get("/{dataset_id}/purchase_orders/{po_id}/export")
async def export_purchase_order_route(
    dataset_id: str,
    po_id: str,
    format: Literal["csv", "edi850"] = Query(default="csv"),
):
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.po_export import export_csv, export_edi850
    try:
        if format == "csv":
            fname, body = export_csv(dataset_id, po_id)
            media = "text/csv"
        else:
            fname, body = export_edi850(dataset_id, po_id)
            media = "application/edi-x12"
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(
        content=body, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ---------- Phase 3: Supplier scorecards ----------


@router.get("/{dataset_id}/suppliers")
async def list_suppliers(dataset_id: str) -> list[dict]:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.supplier_metrics import compute_supplier_scorecards
    with open_dataset(dataset_id, read_only=True) as conn:
        scorecards = compute_supplier_scorecards(conn)
    return [s.__dict__ for s in scorecards]


@router.get("/{dataset_id}/suppliers/{supplier_id}")
async def get_supplier(dataset_id: str, supplier_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.supplier_metrics import get_supplier_detail
    with open_dataset(dataset_id, read_only=True) as conn:
        detail = get_supplier_detail(conn, supplier_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"supplier '{supplier_id}' not found")
    return detail


# ---------- Phase 3: Service-level frontier ----------


@router.get("/{dataset_id}/skus/{sku_id}/frontier")
async def get_frontier(dataset_id: str, sku_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.frontier import compute_frontier
    try:
        return compute_frontier(dataset_id, sku_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ---------- Phase 4: Stress test + working capital ----------


class StressTestBody(BaseModel):
    lead_time_multiplier: float = 1.0
    demand_multiplier: float = 1.0
    service_level: float | None = None
    n_simulations: int | None = None


@router.post("/{dataset_id}/stress_test")
async def post_stress_test(dataset_id: str, body: StressTestBody) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.stress_test import run_stress_test
    return run_stress_test(
        dataset_id,
        lead_time_multiplier=body.lead_time_multiplier,
        demand_multiplier=body.demand_multiplier,
        service_level=body.service_level,
    )


@router.get("/{dataset_id}/working_capital")
async def get_working_capital(dataset_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.working_capital import compute_working_capital
    return compute_working_capital(dataset_id)


# ---------- Phase 3: Forecast decomposition + leaderboard ----------


@router.get("/{dataset_id}/skus/{sku_id}/decomposition")
async def get_decomposition(dataset_id: str, sku_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.forecasting.decompose import decompose_sku
    try:
        return decompose_sku(dataset_id, sku_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/{dataset_id}/skus/{sku_id}/leaderboard")
async def get_leaderboard(dataset_id: str, sku_id: str) -> list[dict]:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.forecasting.leaderboard import compute_leaderboard
    return compute_leaderboard(dataset_id, sku_id)


# ---------- Agentic: Anomaly Explainer + Auto-Plan ----------


class AnomalyExplainBody(BaseModel):
    anchor_date: str | None = None
    severity_threshold: float = 2.5


@router.post("/{dataset_id}/skus/{sku_id}/anomaly_explain")
async def post_anomaly_explain(
    dataset_id: str,
    sku_id: str,
    body: AnomalyExplainBody | None = None,
) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.llm.anomaly_explainer import explain_anomaly_for_sku
    body = body or AnomalyExplainBody()
    return explain_anomaly_for_sku(
        dataset_id, sku_id,
        anchor_date=body.anchor_date,
        severity_threshold=body.severity_threshold,
    )


class AutoPlanBody(BaseModel):
    limit: int = 50
    max_suppliers: int = 8


@router.post("/{dataset_id}/reorder/auto_plan")
async def post_auto_plan(dataset_id: str, body: AutoPlanBody | None = None) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.llm.auto_plan import auto_plan_week
    body = body or AutoPlanBody()
    return auto_plan_week(dataset_id, limit=body.limit, max_suppliers=body.max_suppliers)


class AcceptDraftLine(BaseModel):
    sku_id: str
    qty: float
    rationale: str | None = None


class AcceptDraftPO(BaseModel):
    supplier_id: str | None = None
    supplier_name: str | None = None
    lines: list[AcceptDraftLine]
    expedite: bool = False
    rationale: str | None = None
    joint_replen_group: str | None = None


class AcceptPlanBody(BaseModel):
    draft_pos: list[AcceptDraftPO]


@router.post("/{dataset_id}/reorder/auto_plan/accept")
async def post_auto_plan_accept(dataset_id: str, body: AcceptPlanBody) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.inventory.purchase_orders import draft_purchase_order_multi_line
    created: list[str] = []
    errors: list[dict] = []
    for draft in body.draft_pos:
        try:
            po = draft_purchase_order_multi_line(
                dataset_id,
                supplier_id=draft.supplier_id,
                supplier_name=draft.supplier_name,
                lines=[(l.sku_id, l.qty) for l in draft.lines],
                expedite_flag=draft.expedite,
                joint_replen_group=draft.joint_replen_group,
                notes=draft.rationale,
            )
            created.append(po.po_id)
        except Exception as e:
            errors.append({"supplier_name": draft.supplier_name, "error": f"{type(e).__name__}: {e}"})
    return {"created_po_ids": created, "errors": errors}


# ---------- Phase 5: Insights ----------


@router.get("/{dataset_id}/insights")
async def get_insights(dataset_id: str) -> dict:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.insights.compute import compute_insights
    insights = compute_insights(dataset_id)
    return {"insights": insights}


@router.get("/{dataset_id}/aggregate_stats", response_model=AggregateStats)
async def aggregate_stats(dataset_id: str) -> AggregateStats:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel").fetchdf()
    if panel.empty:
        raise HTTPException(status_code=404, detail="dataset has no rows")

    frequency = infer_frequency(panel["date"]) or "W"
    annualization = {"D": 365, "W": 52, "M": 12}[frequency]
    assignments = classify_abc_xyz(panel, annualization_factor=annualization)
    abc_counts = {"A": 0, "B": 0, "C": 0}
    xyz_counts = {"X": 0, "Y": 0, "Z": 0}
    for a in assignments:
        abc_counts[a.abc] += 1
        xyz_counts[a.xyz] += 1
    heatmap = heatmap_counts(assignments)
    total_revenue = sum(a.revenue_annual for a in assignments)

    on_hand_total: float | None = None
    avg_doc: float | None = None
    if "on_hand" in panel.columns and panel["on_hand"].notna().any():
        last = panel.sort_values("date").groupby("sku_id").tail(1)
        if "unit_cost" in panel.columns and panel["unit_cost"].notna().any():
            inv_value = (last["on_hand"].fillna(0) * last["unit_cost"].fillna(0)).sum()
            on_hand_total = float(inv_value)
        recent = panel.groupby("sku_id").apply(lambda g: g.tail(8)["demand"].mean(), include_groups=False)
        period_days = {"D": 1.0, "W": 7.0, "M": 30.0}[frequency]
        coverage_per_sku = []
        for sku_id_, oh in last.set_index("sku_id")["on_hand"].items():
            mean_d = recent.get(sku_id_, 0.0)
            if pd.notna(oh) and mean_d > 0:
                coverage_per_sku.append(float(oh) / mean_d * period_days)
        if coverage_per_sku:
            avg_doc = float(np.mean(coverage_per_sku))

    settings = get_settings()
    report_path = settings.data_path / "reports" / f"{dataset_id}.json"
    n_low_history = 0
    if report_path.exists():
        report = DataQualityReport.model_validate_json(report_path.read_text())
        n_low_history = len(report.skus_low_history)

    return AggregateStats(
        dataset_id=dataset_id,
        n_skus=int(panel["sku_id"].nunique()),
        total_revenue_annual=round(total_revenue, 2),
        total_inventory_value=on_hand_total,
        avg_days_of_cover=round(avg_doc, 1) if avg_doc is not None else None,
        pct_stockout_risk_high=None,
        abc_counts=abc_counts,
        xyz_counts=xyz_counts,
        abc_xyz_heatmap=heatmap,
        n_skus_low_history=n_low_history,
    )
