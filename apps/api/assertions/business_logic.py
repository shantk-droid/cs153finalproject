"""Business-logic assertion layer — soft fails. Runs after the schema layer passes.

These don't block ingest; they surface as warnings the user can override.
Statistical-anomaly checks vs M5 distributions live in assertions/statistical.py (Day 9).
"""

from __future__ import annotations

import pandas as pd

from apps.api.assertions.schemas import Assertion, Severity


def _example_rows(df: pd.DataFrame, mask: pd.Series, k: int = 3) -> list[dict]:
    if not mask.any():
        return []
    rows = df.loc[mask].head(k)
    out: list[dict] = []
    for _, row in rows.iterrows():
        d: dict = {}
        for c, v in row.items():
            if isinstance(v, pd.Timestamp):
                d[c] = v.isoformat()
            elif pd.isna(v):
                d[c] = None
            elif hasattr(v, "item"):
                d[c] = v.item()
            else:
                d[c] = v
        out.append(d)
    return out


def check_negative_demand(df: pd.DataFrame) -> list[Assertion]:
    mask = df["demand"] < 0
    if not mask.any():
        return []
    n = int(mask.sum())
    return [Assertion(
        code="NEGATIVE_DEMAND",
        severity=Severity.soft,
        field="demand",
        message=f"{n} rows have negative demand. We treat these as returns and net them into demand. Override if these are genuine demand entries.",
        offending_examples=_example_rows(df, mask),
        offending_row_count=n,
        skus_affected=int(df.loc[mask, "sku_id"].nunique()),
    )]


def check_price_below_cost(df: pd.DataFrame) -> list[Assertion]:
    if "unit_price" not in df.columns or "unit_cost" not in df.columns:
        return []
    valid = df[["unit_price", "unit_cost"]].dropna()
    if valid.empty:
        return []
    mask = (df["unit_price"] < df["unit_cost"]) & df["unit_price"].notna() & df["unit_cost"].notna()
    pct = mask.sum() / max(1, valid.shape[0])
    if pct < 0.05:
        return []
    n = int(mask.sum())
    return [Assertion(
        code="PRICE_BELOW_COST",
        severity=Severity.soft,
        field="unit_price",
        message=f"{n} rows ({pct:.1%}) have unit_price < unit_cost. Likely a unit error or markdown event.",
        offending_examples=_example_rows(df, mask),
        offending_row_count=n,
        skus_affected=int(df.loc[mask, "sku_id"].nunique()),
    )]


def check_lead_time_outliers(df: pd.DataFrame) -> list[Assertion]:
    if "lead_time_days" not in df.columns:
        return []
    bad = (df["lead_time_days"] > 365) | (df["lead_time_days"] < 0)
    bad &= df["lead_time_days"].notna()
    if not bad.any():
        return []
    n = int(bad.sum())
    return [Assertion(
        code="LEAD_TIME_OUT_OF_RANGE",
        severity=Severity.soft,
        field="lead_time_days",
        message=f"{n} rows have lead_time_days outside [0, 365]. Likely a unit error (e.g. weeks vs days) or stale data.",
        offending_examples=_example_rows(df, bad),
        offending_row_count=n,
        skus_affected=int(df.loc[bad, "sku_id"].nunique()),
    )]


def check_demand_spikes(df: pd.DataFrame, window: int = 90, multiplier: float = 10.0) -> list[Assertion]:
    """Per-SKU demand spike vs rolling-90 median; large multipliers often = casepack/unit errors."""
    g = df.groupby("sku_id", group_keys=False)
    rolling_median = g["demand"].transform(lambda s: s.rolling(window=window, min_periods=10).median())
    spike_mask = (df["demand"] > multiplier * rolling_median) & rolling_median.notna() & (rolling_median > 0)
    if not spike_mask.any():
        return []
    n = int(spike_mask.sum())
    return [Assertion(
        code="DEMAND_SPIKE_OUTLIER",
        severity=Severity.soft,
        field="demand",
        message=f"{n} rows have demand >{multiplier}× the rolling-{window} median for that SKU. Often a casepack/unit error.",
        offending_examples=_example_rows(df, spike_mask),
        offending_row_count=n,
        skus_affected=int(df.loc[spike_mask, "sku_id"].nunique()),
    )]


def check_on_hand_implausible(df: pd.DataFrame) -> list[Assertion]:
    if "on_hand" not in df.columns:
        return []
    on_hand_present = df.dropna(subset=["on_hand"])
    if on_hand_present.empty:
        return []
    max_demand = df.groupby("sku_id")["demand"].max()
    on_hand_per_sku = on_hand_present.groupby("sku_id")["on_hand"].last()
    flagged_skus = on_hand_per_sku[on_hand_per_sku > 365 * max_demand].index.tolist()
    if not flagged_skus:
        return []
    sample = df[df["sku_id"].isin(flagged_skus[:3])].drop_duplicates(subset=["sku_id"], keep="last")
    return [Assertion(
        code="ON_HAND_IMPLAUSIBLE",
        severity=Severity.soft,
        field="on_hand",
        message=f"{len(flagged_skus)} SKUs have on_hand > 365× their max daily demand. Likely a stale snapshot or unit error.",
        offending_examples=_example_rows(sample, sample.index.to_series().isin(sample.index)),
        offending_row_count=int(df["sku_id"].isin(flagged_skus).sum()),
        skus_affected=len(flagged_skus),
    )]


def check_date_gaps(df: pd.DataFrame, gap_threshold_periods: int = 5) -> list[Assertion]:
    """Each SKU's date series should be contiguous within its active window."""
    if df.empty:
        return []
    issues_per_sku = []
    for sku, g in df.groupby("sku_id"):
        dates = g["date"].sort_values().drop_duplicates()
        if len(dates) < 3:
            continue
        diffs = dates.diff().dt.days.dropna()
        median = diffs.median()
        if median <= 0:
            continue
        big_gaps = (diffs > gap_threshold_periods * median).sum()
        if big_gaps > 0:
            issues_per_sku.append((sku, int(big_gaps)))
    if not issues_per_sku:
        return []
    sample_skus = [s for s, _ in issues_per_sku[:3]]
    sample_rows = df[df["sku_id"].isin(sample_skus)].drop_duplicates(subset=["sku_id"], keep="first")
    return [Assertion(
        code="DATE_GAPS_IN_ACTIVE_WINDOW",
        severity=Severity.soft,
        field="date",
        message=f"{len(issues_per_sku)} SKUs have date gaps >5× their typical period inside their active window.",
        offending_examples=_example_rows(sample_rows, sample_rows.index.to_series().isin(sample_rows.index)),
        offending_row_count=int(df["sku_id"].isin([s for s, _ in issues_per_sku]).sum()),
        skus_affected=len(issues_per_sku),
    )]


def run_all(df: pd.DataFrame) -> list[Assertion]:
    """Run every business-logic check. Each returns 0 or 1 Assertion."""
    out: list[Assertion] = []
    out += check_negative_demand(df)
    out += check_price_below_cost(df)
    out += check_lead_time_outliers(df)
    out += check_demand_spikes(df)
    out += check_on_hand_implausible(df)
    out += check_date_gaps(df)
    return out
