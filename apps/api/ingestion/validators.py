"""Schema layer — hard-fail validation. Runs after the user confirms a column mapping."""

from __future__ import annotations

import pandas as pd

from apps.api.assertions.schemas import Assertion, Severity
from apps.api.ingestion.schemas import REQUIRED_FIELDS, ColumnMapping


def _example_rows(df: pd.DataFrame, mask: pd.Series, k: int = 3) -> list[dict]:
    if not mask.any():
        return []
    rows = df.loc[mask].head(k)
    return [{c: (None if pd.isna(v) else _coerce_jsonable(v)) for c, v in row.items()} for _, row in rows.iterrows()]


def _coerce_jsonable(v):
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v


def apply_mapping(df: pd.DataFrame, mapping: ColumnMapping) -> pd.DataFrame:
    """Rename user columns to canonical names. Drops user columns that aren't mapped."""
    rename: dict[str, str] = {}
    for canon, file_col in mapping.as_dict().items():
        if file_col is not None:
            if file_col not in df.columns:
                raise ValueError(f"mapped column '{file_col}' not in file columns: {list(df.columns)}")
            rename[file_col] = canon
    out = df[list(rename.keys())].rename(columns=rename).copy()
    return out


def validate_schema(df: pd.DataFrame, mapping: ColumnMapping) -> list[Assertion]:
    """Hard-fail checks. Any returned Assertion with severity=hard means ingest is blocked."""
    issues: list[Assertion] = []

    for canon in REQUIRED_FIELDS:
        if mapping.as_dict().get(canon) is None:
            issues.append(Assertion(
                code="MISSING_REQUIRED_MAPPING",
                severity=Severity.hard,
                field=canon,
                message=f"Required field '{canon}' is not mapped to a file column.",
                offending_examples=[],
                offending_row_count=0,
            ))

    if any(i.severity == Severity.hard for i in issues):
        return issues

    canonical = apply_mapping(df, mapping)

    sku_unparseable = canonical["sku_id"].isna() | (canonical["sku_id"].astype(str).str.strip() == "")
    if sku_unparseable.any():
        issues.append(Assertion(
            code="SKU_ID_NULL_OR_BLANK",
            severity=Severity.hard,
            field="sku_id",
            message=f"{int(sku_unparseable.sum())} rows have null or blank sku_id.",
            offending_examples=_example_rows(canonical, sku_unparseable),
            offending_row_count=int(sku_unparseable.sum()),
        ))

    parsed_dates = pd.to_datetime(canonical["date"], errors="coerce")
    bad_dates = parsed_dates.isna()
    if bad_dates.any():
        issues.append(Assertion(
            code="DATE_PARSE_FAILED",
            severity=Severity.hard,
            field="date",
            message=f"{int(bad_dates.sum())} rows have unparseable dates.",
            offending_examples=_example_rows(canonical, bad_dates),
            offending_row_count=int(bad_dates.sum()),
        ))

    demand_numeric = pd.to_numeric(canonical["demand"], errors="coerce")
    bad_demand = demand_numeric.isna()
    if bad_demand.any():
        issues.append(Assertion(
            code="DEMAND_NOT_NUMERIC",
            severity=Severity.hard,
            field="demand",
            message=f"{int(bad_demand.sum())} rows have non-numeric demand.",
            offending_examples=_example_rows(canonical, bad_demand),
            offending_row_count=int(bad_demand.sum()),
        ))

    if not bad_dates.any() and not sku_unparseable.any():
        canonical = canonical.copy()
        canonical["date"] = parsed_dates
        canonical["sku_id"] = canonical["sku_id"].astype(str).str.strip().str.upper()
        dup_mask = canonical.duplicated(subset=["sku_id", "date"], keep=False)
        if dup_mask.any():
            n = int(dup_mask.sum())
            issues.append(Assertion(
                code="SKU_DATE_DUPLICATES",
                severity=Severity.hard,
                field=None,
                message=f"{n} rows are part of (sku_id, date) duplicate groups; each combination must be unique.",
                offending_examples=_example_rows(canonical, dup_mask),
                offending_row_count=n,
            ))

    return issues


def normalize_canonical(df: pd.DataFrame, mapping: ColumnMapping) -> pd.DataFrame:
    """Apply mapping + dtype normalization. Assumes validate_schema has passed."""
    canonical = apply_mapping(df, mapping)
    canonical["date"] = pd.to_datetime(canonical["date"], errors="raise").dt.normalize()
    canonical["sku_id"] = canonical["sku_id"].astype(str).str.strip().str.upper()
    canonical["demand"] = pd.to_numeric(canonical["demand"], errors="raise")

    for opt in ("on_hand", "lead_time_days", "unit_cost", "unit_price"):
        if opt in canonical.columns:
            canonical[opt] = pd.to_numeric(canonical[opt], errors="coerce")
    for opt in ("supplier", "category"):
        if opt in canonical.columns:
            canonical[opt] = canonical[opt].astype(str).str.strip()
            canonical.loc[canonical[opt].isin(("nan", "NaN", "None", "")), opt] = None

    canonical = canonical.sort_values(["sku_id", "date"]).reset_index(drop=True)
    return canonical


def infer_frequency(dates: pd.Series) -> str | None:
    """Best-effort frequency inference from a sorted date series.

    Returns 'D', 'W', 'M', or None.
    """
    s = pd.to_datetime(dates).drop_duplicates().sort_values()
    if len(s) < 3:
        return None
    diffs = s.diff().dropna().dt.days
    median = diffs.median()
    if 0.5 <= median <= 1.5:
        return "D"
    if 6 <= median <= 8:
        return "W"
    if 28 <= median <= 32:
        return "M"
    return None
