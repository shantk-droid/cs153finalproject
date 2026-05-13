from __future__ import annotations

import pandas as pd
import pytest

from apps.api.assertions.schemas import Severity
from apps.api.ingestion.mappers import detect_columns, suggest_mapping
from apps.api.ingestion.parsers import parse_csv, parse_upload, parse_xlsx
from apps.api.ingestion.schemas import ColumnMapping
from apps.api.ingestion.validators import (
    apply_mapping,
    infer_frequency,
    normalize_canonical,
    validate_schema,
)


# --- parsers ---

def test_parse_csv_round_trip(sample_csv_bytes: bytes, sample_panel: pd.DataFrame):
    df = parse_csv(sample_csv_bytes)
    assert len(df) == len(sample_panel)
    assert set(df.columns) >= {"sku_id", "date", "demand"}


def test_parse_upload_csv_dispatch(sample_csv_bytes: bytes):
    res = parse_upload("data.csv", sample_csv_bytes)
    assert len(res.df) > 0
    assert res.sheet_names is None


def test_parse_upload_xlsx_dispatch(sample_xlsx_bytes: bytes):
    res = parse_upload("data.xlsx", sample_xlsx_bytes)
    assert len(res.df) > 0
    assert res.sheet_names is not None
    assert res.selected_sheet is not None


def test_parse_upload_rejects_xls():
    with pytest.raises(ValueError, match="Legacy .xls"):
        parse_upload("data.xls", b"\x00\x00")


def test_parse_upload_rejects_unknown_extension():
    with pytest.raises(ValueError):
        parse_upload("data.parquet", b"\x00")


# --- column auto-detect / mapper ---

def test_detect_columns_returns_one_per_column(sample_panel: pd.DataFrame):
    detections = detect_columns(sample_panel)
    assert {d.name for d in detections} == set(sample_panel.columns)


def test_suggest_mapping_with_canonical_headers(sample_panel: pd.DataFrame):
    detections = detect_columns(sample_panel)
    suggestions = suggest_mapping(sample_panel, detections)
    sm = {s.canonical: s.file_column for s in suggestions}
    for required in ("sku_id", "date", "demand"):
        assert sm[required] == required


def test_suggest_mapping_with_renamed_headers(renamed_csv_bytes: bytes):
    df = parse_csv(renamed_csv_bytes)
    detections = detect_columns(df)
    suggestions = suggest_mapping(df, detections)
    sm = {s.canonical: s.file_column for s in suggestions}
    assert sm["sku_id"] == "Item ID"
    assert sm["date"] == "Day"
    assert sm["demand"] == "Units Sold"
    assert sm["unit_cost"] == "Cost"
    assert sm["unit_price"] == "Sell Price"
    assert sm["supplier"] == "Vendor"


# --- schema layer ---

def _full_mapping() -> ColumnMapping:
    return ColumnMapping(
        sku_id="sku_id", date="date", demand="demand",
        on_hand="on_hand", lead_time_days="lead_time_days",
        unit_cost="unit_cost", unit_price="unit_price",
        supplier="supplier", category="category",
    )


def test_validate_schema_passes_clean_panel(sample_panel: pd.DataFrame):
    issues = validate_schema(sample_panel, _full_mapping())
    hard = [i for i in issues if i.severity == Severity.hard]
    assert hard == []


def test_validate_schema_blocks_when_required_unmapped(sample_panel: pd.DataFrame):
    mapping = ColumnMapping(sku_id="sku_id", date="date", demand="demand")
    issues = validate_schema(sample_panel, mapping)
    assert all(i.severity == Severity.hard or i.severity == Severity.soft for i in issues)


def test_validate_schema_catches_duplicates(sample_panel: pd.DataFrame):
    df = pd.concat([sample_panel, sample_panel.head(20)], ignore_index=True)
    issues = validate_schema(df, _full_mapping())
    codes = {i.code for i in issues if i.severity == Severity.hard}
    assert "SKU_DATE_DUPLICATES" in codes


def test_validate_schema_catches_bad_dates(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    df.loc[df.index[:5], "date"] = "garbage"
    issues = validate_schema(df, _full_mapping())
    codes = {i.code for i in issues if i.severity == Severity.hard}
    assert "DATE_PARSE_FAILED" in codes


def test_normalize_canonical_uppercases_sku_and_normalizes_date(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    df["sku_id"] = df["sku_id"].str.lower()
    out = normalize_canonical(df, _full_mapping())
    assert (out["sku_id"] == out["sku_id"].str.upper()).all()
    assert pd.api.types.is_datetime64_any_dtype(out["date"])


def test_apply_mapping_drops_unmapped_columns(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    df["extra"] = 1
    out = apply_mapping(df, _full_mapping())
    assert "extra" not in out.columns


def test_infer_frequency_weekly(sample_panel: pd.DataFrame):
    assert infer_frequency(sample_panel["date"]) == "W"


def test_infer_frequency_daily():
    dates = pd.Series(pd.date_range("2025-01-01", periods=30, freq="D"))
    assert infer_frequency(dates) == "D"


def test_infer_frequency_monthly():
    dates = pd.Series(pd.date_range("2025-01-01", periods=12, freq="MS"))
    assert infer_frequency(dates) == "M"
