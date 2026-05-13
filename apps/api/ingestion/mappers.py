"""Column auto-detection.

Uses a curated synonym table per canonical field plus difflib similarity to handle typos
and unknown variants. Returns a confidence score per (canonical, file_column) pair.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import pandas as pd

from apps.api.ingestion.schemas import (
    CANONICAL_FIELDS,
    REQUIRED_FIELDS,
    CanonicalField,
    ColumnDetection,
    SuggestedMappingItem,
)

# Hand-curated synonyms — everything is lowercased + non-alphanumeric stripped before match.
SYNONYMS: dict[CanonicalField, list[str]] = {
    "sku_id": ["sku", "skuid", "sku_id", "item", "itemid", "item_id", "product", "productid",
               "product_id", "code", "partnum", "part_no", "ean", "upc", "asin", "id"],
    "date": ["date", "dt", "day", "period", "ds", "timestamp", "time", "weekstart", "week",
             "month", "yearmonth", "ym"],
    "demand": ["demand", "qty", "quantity", "units", "sales", "sold", "shipped",
               "orderqty", "order_qty", "unitssold", "units_sold"],
    "on_hand": ["onhand", "on_hand", "stock", "inventory", "inv", "available", "soh",
                "stockonhand", "stock_on_hand"],
    "lead_time_days": ["leadtime", "lead_time", "lead_time_days", "leadtimedays", "lt", "ltdays"],
    "unit_cost": ["unitcost", "unit_cost", "cost", "cogs", "buyprice", "purchaseprice"],
    "unit_price": ["unitprice", "unit_price", "price", "sellprice", "sell_price", "retail",
                   "retail_price", "list_price"],
    "supplier": ["supplier", "vendor", "vendorid", "vendor_id", "manufacturer", "mfg", "brand"],
    "category": ["category", "cat", "department", "dept", "deptid", "dept_id", "family",
                 "categoryid", "category_id", "group", "subcategory"],
}


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _best_synonym_score(canonical: CanonicalField, header: str) -> float:
    h = _normalize(header)
    if not h:
        return 0.0
    best = 0.0
    for syn in SYNONYMS[canonical]:
        s = _normalize(syn)
        if h == s:
            return 1.0
        if h.startswith(s) or s.startswith(h):
            best = max(best, 0.85)
        if s in h or h in s:
            best = max(best, 0.7)
        sim = SequenceMatcher(None, h, s).ratio()
        best = max(best, sim)
    return best


def _series_dtype_label(series: pd.Series) -> str:
    sample = series.dropna().head(30)
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_string_dtype(series) or series.dtype == object:
        as_str = sample.astype(str)
        try:
            parsed = pd.to_datetime(as_str, errors="raise")
            if parsed.notna().all():
                return "date"
        except (ValueError, TypeError):
            pass
        try:
            pd.to_numeric(as_str, errors="raise")
            return "float" if any("." in v for v in as_str) else "integer"
        except (ValueError, TypeError):
            pass
        return "string"
    return "unknown"


def detect_columns(df: pd.DataFrame, sample_size: int = 5) -> list[ColumnDetection]:
    out: list[ColumnDetection] = []
    n = max(1, len(df))
    for col in df.columns:
        s = df[col]
        dtype = _series_dtype_label(s)
        unique = int(s.nunique(dropna=True))
        sample_values = [str(v) for v in s.dropna().head(sample_size).tolist()]
        out.append(ColumnDetection(
            name=str(col),
            dtype=dtype,  # type: ignore[arg-type]
            null_pct=round(s.isna().mean(), 4),
            unique_pct=round(unique / n, 4),
            sample_values=sample_values,
        ))
    return out


def suggest_mapping(df: pd.DataFrame, detections: list[ColumnDetection]) -> list[SuggestedMappingItem]:
    """Return the highest-confidence file column for each canonical field.

    Greedy: each file column can only map to one canonical field. Required fields take priority.
    """
    file_cols = [d.name for d in detections]
    score_grid: dict[CanonicalField, dict[str, float]] = {}
    for canon in CANONICAL_FIELDS:
        score_grid[canon] = {fc: _best_synonym_score(canon, fc) for fc in file_cols}

    # Bias toward dtype consistency.
    for d in detections:
        dt = d.dtype
        if dt == "date":
            score_grid["date"][d.name] = min(1.0, score_grid["date"][d.name] + 0.2)
        if dt in {"integer", "float"}:
            for canon in ("demand", "on_hand", "lead_time_days", "unit_cost", "unit_price"):
                score_grid[canon][d.name] = min(1.0, score_grid[canon][d.name] + 0.05)
        if dt == "string":
            for canon in ("sku_id", "supplier", "category"):
                score_grid[canon][d.name] = min(1.0, score_grid[canon][d.name] + 0.05)

    result: list[SuggestedMappingItem] = []
    used: set[str] = set()
    canon_order = list(REQUIRED_FIELDS) + [c for c in CANONICAL_FIELDS if c not in REQUIRED_FIELDS]
    for canon in canon_order:
        candidates = sorted(
            ((fc, sc) for fc, sc in score_grid[canon].items() if fc not in used),
            key=lambda x: x[1], reverse=True,
        )
        if not candidates:
            result.append(SuggestedMappingItem(canonical=canon, file_column=None, confidence=0.0))
            continue
        best_col, best_score = candidates[0]
        threshold = 0.55 if canon in REQUIRED_FIELDS else 0.7
        if best_score < threshold:
            result.append(SuggestedMappingItem(canonical=canon, file_column=None, confidence=round(best_score, 3)))
        else:
            result.append(SuggestedMappingItem(canonical=canon, file_column=best_col, confidence=round(best_score, 3)))
            used.add(best_col)

    result.sort(key=lambda x: list(CANONICAL_FIELDS).index(x.canonical))
    return result
