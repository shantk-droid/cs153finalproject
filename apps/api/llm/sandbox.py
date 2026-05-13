"""Restricted dataframe query — answers ad-hoc analytical questions safely.

NOT a Python sandbox. We expose a small JSON-shaped query language that compiles to specific
pandas operations, so the LLM can never execute arbitrary code:

    {
      "filter": [{"col":"category", "op":"==", "value":"FOODS_3"},
                 {"col":"demand",   "op":">=", "value":100}],
      "groupby": ["supplier"],                       // optional
      "aggregate": {"demand": "sum", "sku_id": "nunique"},  // {col: aggfunc}
      "sort_by": "demand", "sort_dir": "desc",
      "limit": 20
    }

If `groupby` is omitted but `aggregate` is present, we aggregate the whole filtered frame.
If both are omitted, return the filtered+sorted+limited frame with selected columns.
"""

from __future__ import annotations

import operator
from typing import Any, Iterable

import pandas as pd

ALLOWED_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">":  operator.gt,
    ">=": operator.ge,
    "<":  operator.lt,
    "<=": operator.le,
    "in": lambda a, b: a.isin(b) if isinstance(b, (list, tuple, set)) else a == b,
    "not in": lambda a, b: ~a.isin(b) if isinstance(b, (list, tuple, set)) else a != b,
    "contains": lambda a, b: a.astype(str).str.contains(str(b), case=False, na=False),
    "is_null": lambda a, _b: a.isna(),
    "not_null": lambda a, _b: a.notna(),
}

ALLOWED_AGGS = {"sum", "mean", "median", "min", "max", "count", "nunique", "std", "first", "last"}

ALLOWED_COLS = {
    "sku_id", "date", "demand", "on_hand", "lead_time_days",
    "unit_cost", "unit_price", "supplier", "category",
}

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class SandboxQueryError(ValueError):
    pass


def _validate_col(col: str) -> str:
    if col not in ALLOWED_COLS:
        raise SandboxQueryError(f"unknown column '{col}'. Allowed: {sorted(ALLOWED_COLS)}")
    return col


def _apply_filter(df: pd.DataFrame, filters: Iterable[dict]) -> pd.DataFrame:
    out = df
    for f in filters:
        col = _validate_col(str(f.get("col", "")))
        op = f.get("op", "==")
        if op not in ALLOWED_OPS:
            raise SandboxQueryError(f"unsupported op '{op}'. Allowed: {sorted(ALLOWED_OPS)}")
        value = f.get("value")
        mask = ALLOWED_OPS[op](out[col], value)
        out = out[mask]
    return out


def _apply_aggregate(df: pd.DataFrame, groupby: list[str] | None, aggregate: dict[str, str]) -> pd.DataFrame:
    for col in aggregate:
        _validate_col(col)
        if aggregate[col] not in ALLOWED_AGGS:
            raise SandboxQueryError(f"unsupported aggregate '{aggregate[col]}'. Allowed: {sorted(ALLOWED_AGGS)}")
    if groupby:
        for c in groupby:
            _validate_col(c)
        return df.groupby(groupby, dropna=False).agg(aggregate).reset_index()
    return df.agg(aggregate).to_frame().T


def _to_records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return [
        {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for k, v in row.items()}
        for row in out.to_dict(orient="records")
    ]


def execute_query(panel: pd.DataFrame, query: dict) -> dict:
    """Run a sandboxed query against the panel. Returns rows + metadata."""
    df = panel
    if (filters := query.get("filter")):
        if not isinstance(filters, list):
            raise SandboxQueryError("'filter' must be a list of {col, op, value} objects")
        df = _apply_filter(df, filters)

    if (aggregate := query.get("aggregate")):
        if not isinstance(aggregate, dict):
            raise SandboxQueryError("'aggregate' must be an object {col: aggfunc}")
        groupby = query.get("groupby")
        if groupby is not None and not isinstance(groupby, list):
            raise SandboxQueryError("'groupby' must be a list of column names")
        df = _apply_aggregate(df, groupby, aggregate)

    sort_by = query.get("sort_by")
    if sort_by:
        if sort_by not in df.columns:
            raise SandboxQueryError(f"sort_by column '{sort_by}' not present after aggregation")
        df = df.sort_values(sort_by, ascending=(query.get("sort_dir", "desc") == "asc"))

    limit = int(query.get("limit", DEFAULT_LIMIT))
    if limit < 1 or limit > MAX_LIMIT:
        raise SandboxQueryError(f"limit must be in [1, {MAX_LIMIT}]")
    truncated = len(df) > limit
    df = df.head(limit)

    return {
        "rows": _to_records(df),
        "n_rows_returned": len(df),
        "truncated": truncated,
    }
