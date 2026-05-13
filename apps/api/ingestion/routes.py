"""FastAPI router for /datasets ingestion endpoints."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address

from apps.api.assertions.schemas import DataQualityReport, Severity
from apps.api.assertions.score import compute_dq_report
from apps.api.config import get_settings
from apps.api.db import dataset_path, ensure_all_tables, ensure_panel_table, open_dataset
from apps.api.ingestion.connectors.shopify import (
    detect_shopify,
    transform_shopify_to_panel,
)
from apps.api.ingestion.demo import create_demo_dataset, list_templates
from apps.api.ingestion.mappers import detect_columns, suggest_mapping
from apps.api.ingestion.parsers import parse_upload
from apps.api.ingestion.schemas import (
    ColumnMapping,
    DatasetPreview,
    DatasetSummary,
)
from apps.api.ingestion.storage import (
    DatasetMetadata,
    cleanup_upload,
    load_upload,
    read_dataset_metadata,
    save_upload,
    write_dataset_metadata,
)
from apps.api.ingestion.validators import (
    apply_mapping,
    infer_frequency,
    normalize_canonical,
    validate_schema,
)
from apps.api.inventory.supplier_metrics import derive_suppliers_from_panel
from apps.api.profiles import list_profiles, match_profile
from apps.api.assertions.statistical import panel_metric_medians

router = APIRouter(prefix="/datasets", tags=["datasets"])
limiter = Limiter(key_func=get_remote_address, enabled=os.environ.get("RATELIMIT_DISABLED") != "1")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_TOTAL_ROWS = 100_000


def _df_to_records_jsonable(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    return [
        {k: (None if pd.isna(v) else v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]


@router.post("/upload", response_model=DatasetPreview)
@limiter.limit("20/hour")
async def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    sheet_override: str | None = Form(default=None),
) -> DatasetPreview:
    if file.filename is None:
        raise HTTPException(status_code=400, detail="file must have a filename")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file is {len(content)/1e6:.1f} MB; max is {MAX_UPLOAD_BYTES/1e6:.0f} MB",
        )

    try:
        parsed = parse_upload(file.filename, content, sheet_override=sheet_override)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    df = parsed.df
    if df.empty:
        raise HTTPException(status_code=400, detail="parsed file has 0 rows")

    if len(df) > MAX_TOTAL_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"parsed {len(df):,} rows; max is {MAX_TOTAL_ROWS:,}. Aggregate to weekly/monthly first.",
        )

    # Vendor-connector detection runs before generic column mapping. If we recognize the
    # file as e.g. a Shopify orders export, we transform line-items into the canonical
    # SKU panel and skip the heuristic mapping — saves the user from filling in 9 dropdowns
    # for a format with stable, known column names.
    detected_connector: str | None = None
    if detect_shopify(df):
        try:
            transformed = transform_shopify_to_panel(df)
            if not transformed.empty:
                df = transformed
                detected_connector = "shopify"
        except ValueError:
            # Detection lied; fall through to generic path.
            pass

    detections = detect_columns(df)
    suggested = suggest_mapping(df, detections)

    dataset_id = str(uuid.uuid4())
    # For Shopify, persist the *transformed* panel so confirm() reads canonical columns,
    # not the original line-item rows. Use the same temp-store path with a sentinel filename
    # so we can re-detect on the cached version.
    if detected_connector == "shopify":
        # Re-serialize the transformed panel as CSV for storage. The original upload's
        # filename is preserved in the preview but the stored bytes are the panel CSV.
        panel_csv = df.to_csv(index=False).encode("utf-8")
        save_upload(dataset_id, file.filename, panel_csv, sheet_override=None)
    else:
        save_upload(dataset_id, file.filename, content, sheet_override=parsed.selected_sheet)

    return DatasetPreview(
        dataset_id=dataset_id,
        filename=file.filename,
        n_total_rows=int(len(df)),
        detected_columns=detections,
        suggested_mapping=suggested,
        sample_rows=_df_to_records_jsonable(df.head(20)),
        sheet_names=parsed.sheet_names,
        selected_sheet=parsed.selected_sheet,
        detected_connector=detected_connector,
    )


@router.post("/{dataset_id}/confirm", response_model=DatasetSummary)
async def confirm_dataset(
    dataset_id: str,
    mapping: ColumnMapping,
    profile_id: str = "auto",
) -> DatasetSummary:
    try:
        stored = load_upload(dataset_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    content = stored.file_path.read_bytes()
    try:
        parsed = parse_upload(stored.filename, content, sheet_override=stored.sheet_override)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    df = parsed.df

    try:
        schema_issues = validate_schema(df, mapping)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid column mapping: {e}") from e
    hard_issues = [a for a in schema_issues if a.severity == Severity.hard]
    if hard_issues:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SCHEMA_VALIDATION_FAILED",
                "assertions": [a.model_dump() for a in hard_issues],
            },
        )

    canonical = normalize_canonical(df, mapping)
    canonical_for_dq = canonical.copy()

    auto_detected = profile_id == "auto"
    match_confidence: float | None = None
    if auto_detected:
        medians = panel_metric_medians(canonical_for_dq)
        resolved_id, match_confidence = match_profile(medians)
    else:
        valid_ids = {p.id for p in list_profiles()}
        if profile_id not in valid_ids:
            raise HTTPException(status_code=400, detail=f"unknown profile_id={profile_id!r}; have {sorted(valid_ids)}")
        resolved_id = profile_id

    write_dataset_metadata(DatasetMetadata(
        dataset_id=dataset_id,
        profile_id=resolved_id,
        profile_auto_detected=auto_detected,
        match_confidence=match_confidence,
    ))

    report = compute_dq_report(
        dataset_id,
        canonical_for_dq,
        profile_id=resolved_id,
        schema_assertions=schema_issues,
        profile_auto_detected=auto_detected,
        profile_match_confidence=match_confidence,
    )

    settings = get_settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)
    db_file = dataset_path(dataset_id)
    if db_file.exists():
        db_file.unlink()
    derived_suppliers = derive_suppliers_from_panel(canonical)
    with open_dataset(dataset_id) as conn:
        ensure_all_tables(conn)
        conn.register("panel_in", canonical)
        conn.execute("INSERT INTO panel SELECT * FROM panel_in")
        conn.unregister("panel_in")
        if not derived_suppliers.empty:
            conn.register("suppliers_in", derived_suppliers)
            conn.execute("INSERT INTO suppliers SELECT * FROM suppliers_in")
            conn.unregister("suppliers_in")

    reports_dir = settings.data_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{dataset_id}.json").write_text(report.model_dump_json(indent=2))

    cleanup_upload(dataset_id)

    return DatasetSummary(
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


def _is_legacy_report(raw: dict) -> bool:
    """Detect a DQ report cached under the old M5-band scoring (pre profile-registry)."""
    components = raw.get("components") or []
    if any(c.get("name") == "statistical_fit" for c in components):
        return True
    if raw.get("profile") is None:
        # New schema always populates `profile`. Old schema doesn't have the key at all.
        return True
    for a in raw.get("assertions") or []:
        if a.get("code") == "STATISTICAL_ANOMALY_VS_M5":
            return True
    return False


def _rescore_from_panel(dataset_id: str) -> DataQualityReport:
    """Rebuild the DQ report from the dataset's panel using the current scoring code."""
    db_file = dataset_path(dataset_id)
    if not db_file.exists():
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    with open_dataset(dataset_id, read_only=True) as conn:
        canonical = conn.execute("SELECT * FROM panel ORDER BY sku_id, date").fetchdf()

    meta = read_dataset_metadata(dataset_id)
    auto_detected = meta.profile_auto_detected
    match_confidence = meta.match_confidence
    profile_id = meta.profile_id
    if auto_detected or profile_id == "auto":
        medians = panel_metric_medians(canonical)
        profile_id, match_confidence = match_profile(medians)
        auto_detected = True
        write_dataset_metadata(DatasetMetadata(
            dataset_id=dataset_id,
            profile_id=profile_id,
            profile_auto_detected=True,
            match_confidence=match_confidence,
        ))

    report = compute_dq_report(
        dataset_id,
        canonical,
        profile_id=profile_id,
        profile_auto_detected=auto_detected,
        profile_match_confidence=match_confidence,
    )
    settings = get_settings()
    reports_dir = settings.data_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{dataset_id}.json").write_text(report.model_dump_json(indent=2))
    return report


@router.get("/{dataset_id}/quality", response_model=DataQualityReport)
async def get_dq_report(dataset_id: str, explain: bool = False) -> DataQualityReport:
    settings = get_settings()
    report_path = settings.data_path / "reports" / f"{dataset_id}.json"
    if not report_path.exists():
        # No cached report — rebuild from the panel if the dataset itself exists.
        report = _rescore_from_panel(dataset_id)
    else:
        raw_text = report_path.read_text()
        try:
            raw_dict = json.loads(raw_text)
        except json.JSONDecodeError:
            raw_dict = {}
        if _is_legacy_report(raw_dict):
            # On-the-fly migration: regenerate under the new profile-registry scoring.
            report = _rescore_from_panel(dataset_id)
        else:
            report = DataQualityReport.model_validate_json(raw_text)
    if explain and report.explanations is None:
        from apps.api.assertions.explainer import explain_top_issues
        try:
            explanations = explain_top_issues(report, max_issues=10)
            report.explanations = explanations
        except Exception as e:
            report.explanations = {"_error": f"explanation generation failed: {type(e).__name__}: {e}"}
    return report


@router.get("/profiles")
async def list_reference_profiles() -> dict:
    """List the reference profiles available for distribution scoring."""
    return {
        "profiles": [
            {"id": p.id, "label": p.label, "description": p.description, "version": p.version}
            for p in list_profiles()
        ],
    }


@router.get("/{dataset_id}/metadata", response_model=DatasetMetadata)
async def get_dataset_metadata(dataset_id: str) -> DatasetMetadata:
    db_file = dataset_path(dataset_id)
    if not db_file.exists():
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    return read_dataset_metadata(dataset_id)


@router.patch("/{dataset_id}/metadata", response_model=DatasetMetadata)
async def update_dataset_metadata(dataset_id: str, payload: dict) -> DatasetMetadata:
    """Update profile selection and rescore the DQ report under the new profile."""
    db_file = dataset_path(dataset_id)
    if not db_file.exists():
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")

    new_profile_id = str(payload.get("profile_id", "auto"))

    with open_dataset(dataset_id, read_only=True) as conn:
        canonical = conn.execute("SELECT * FROM panel ORDER BY sku_id, date").fetchdf()

    auto_detected = new_profile_id == "auto"
    match_confidence: float | None = None
    if auto_detected:
        medians = panel_metric_medians(canonical)
        resolved_id, match_confidence = match_profile(medians)
    else:
        valid_ids = {p.id for p in list_profiles()}
        if new_profile_id not in valid_ids:
            raise HTTPException(status_code=400, detail=f"unknown profile_id={new_profile_id!r}; have {sorted(valid_ids)}")
        resolved_id = new_profile_id

    meta = DatasetMetadata(
        dataset_id=dataset_id,
        profile_id=resolved_id,
        profile_auto_detected=auto_detected,
        match_confidence=match_confidence,
    )
    write_dataset_metadata(meta)

    report = compute_dq_report(
        dataset_id,
        canonical,
        profile_id=resolved_id,
        profile_auto_detected=auto_detected,
        profile_match_confidence=match_confidence,
    )
    settings = get_settings()
    reports_dir = settings.data_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{dataset_id}.json").write_text(report.model_dump_json(indent=2))

    return meta


@router.get("/demo/templates")
async def list_demo_templates() -> dict:
    """List available bootstrap templates for the 'See sample data' flow."""
    return {"templates": list_templates()}


@router.post("/demo/{template}", response_model=DatasetSummary)
async def create_demo(template: str, seed: int = 42) -> DatasetSummary:
    """Bootstrap a demo dataset from a synthetic template (panel + suppliers + receipts)."""
    try:
        _, summary = create_demo_dataset(template, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return summary


@router.get("/{dataset_id}", response_model=DatasetSummary)
async def get_dataset_summary(dataset_id: str) -> DatasetSummary:
    db_file = dataset_path(dataset_id)
    if not db_file.exists():
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    with open_dataset(dataset_id, read_only=True) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM panel").fetchone()[0]
        skus = conn.execute("SELECT COUNT(DISTINCT sku_id) FROM panel").fetchone()[0]
        date_min, date_max = conn.execute("SELECT MIN(date), MAX(date) FROM panel").fetchone()
        cats = conn.execute("SELECT COUNT(DISTINCT category) FROM panel WHERE category IS NOT NULL").fetchone()[0]
        sups = conn.execute("SELECT COUNT(DISTINCT supplier) FROM panel WHERE supplier IS NOT NULL").fetchone()[0]
        has_on_hand = conn.execute("SELECT COUNT(*) FROM panel WHERE on_hand IS NOT NULL").fetchone()[0] > 0
        has_lt = conn.execute("SELECT COUNT(*) FROM panel WHERE lead_time_days IS NOT NULL").fetchone()[0] > 0
        has_cost = conn.execute("SELECT COUNT(*) FROM panel WHERE unit_cost IS NOT NULL").fetchone()[0] > 0
        has_price = conn.execute("SELECT COUNT(*) FROM panel WHERE unit_price IS NOT NULL").fetchone()[0] > 0
        dates = conn.execute("SELECT DISTINCT date FROM panel ORDER BY date").fetchdf()

    return DatasetSummary(
        dataset_id=dataset_id,
        n_rows=int(rows),
        n_skus=int(skus),
        date_min=pd.Timestamp(date_min).date(),
        date_max=pd.Timestamp(date_max).date(),
        frequency=infer_frequency(dates["date"]),  # type: ignore[arg-type]
        n_categories=int(cats),
        n_suppliers=int(sups),
        has_on_hand=bool(has_on_hand),
        has_lead_time=bool(has_lt),
        has_unit_cost=bool(has_cost),
        has_unit_price=bool(has_price),
    )
