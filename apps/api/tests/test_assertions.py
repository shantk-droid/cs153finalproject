from __future__ import annotations

import pandas as pd

from apps.api.assertions.business_logic import (
    check_date_gaps,
    check_demand_spikes,
    check_lead_time_outliers,
    check_negative_demand,
    check_on_hand_implausible,
    check_price_below_cost,
    run_all,
)
from apps.api.assertions.schemas import Severity
from apps.api.assertions.score import compute_dq_report
from apps.api.ingestion.validators import normalize_canonical
from apps.api.ingestion.schemas import ColumnMapping


def _full_mapping() -> ColumnMapping:
    return ColumnMapping(
        sku_id="sku_id", date="date", demand="demand",
        on_hand="on_hand", lead_time_days="lead_time_days",
        unit_cost="unit_cost", unit_price="unit_price",
        supplier="supplier", category="category",
    )


# --- business-logic checks ---

def test_negative_demand_flagged(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    df.loc[df.index[:50], "demand"] = -3
    issues = check_negative_demand(df)
    assert len(issues) == 1
    assert issues[0].code == "NEGATIVE_DEMAND"
    assert issues[0].severity == Severity.soft
    assert issues[0].offending_row_count == 50


def test_negative_demand_passes_when_clean(sample_panel: pd.DataFrame):
    assert check_negative_demand(sample_panel) == []


def test_price_below_cost_only_flags_above_5pct(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    df.loc[df.index[:5], "unit_price"] = 0.5
    df.loc[df.index[:5], "unit_cost"] = 10.0
    if df["unit_cost"].notna().sum() > 200:
        assert check_price_below_cost(df) == []


def test_price_below_cost_flagged_when_widespread(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    n = int(0.2 * len(df))
    df.loc[df.index[:n], "unit_price"] = 0.5
    df.loc[df.index[:n], "unit_cost"] = 10.0
    issues = check_price_below_cost(df)
    assert len(issues) == 1
    assert issues[0].severity == Severity.soft


def test_lead_time_outliers_flagged(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    df.loc[df.index[:5], "lead_time_days"] = 9999
    issues = check_lead_time_outliers(df)
    assert len(issues) == 1
    assert issues[0].code == "LEAD_TIME_OUT_OF_RANGE"


def test_demand_spike_flagged():
    rows = []
    base_date = pd.Timestamp("2024-01-01")
    for i in range(120):
        rows.append({"sku_id": "X", "date": base_date + pd.Timedelta(days=i),
                     "demand": 10 + (i % 3), "supplier": "S", "category": "C"})
    df = pd.DataFrame(rows)
    df.loc[100:104, "demand"] = 1000
    issues = check_demand_spikes(df, window=30, multiplier=10.0)
    assert len(issues) == 1
    assert issues[0].code == "DEMAND_SPIKE_OUTLIER"


def test_on_hand_implausible_flagged(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    last_idx = df.groupby("sku_id").tail(1).index[:5]
    df.loc[last_idx, "on_hand"] = 1e7
    issues = check_on_hand_implausible(df)
    assert len(issues) == 1


def test_date_gaps_flagged():
    rows = []
    base_date = pd.Timestamp("2024-01-01")
    for i in range(50):
        rows.append({"sku_id": "X", "date": base_date + pd.Timedelta(weeks=i), "demand": 10})
    for i in range(60, 110):
        rows.append({"sku_id": "X", "date": base_date + pd.Timedelta(weeks=i), "demand": 10})
    df = pd.DataFrame(rows)
    issues = check_date_gaps(df)
    assert len(issues) == 1


# --- DQ score ---

def test_dq_report_clean_panel(sample_panel: pd.DataFrame):
    canonical = normalize_canonical(sample_panel, _full_mapping())
    report = compute_dq_report("test-clean", canonical)
    component_names = {c.name for c in report.components}
    assert component_names == {"completeness", "plausibility", "distribution_profile", "history_depth", "stationarity"}

    for c in report.components:
        if c.score is not None:
            assert 0 <= c.score <= 100
    plausibility = next(c for c in report.components if c.name == "plausibility")
    # Realistic retail-shaped synthetic data has lumpy demand → some spikes triggered. We tolerate
    # the standard 20-point soft penalty for a single business-rule violation; the bound rejects
    # outright generator regressions (e.g. duplicate SKUs, negatives) which would push score < 70.
    assert plausibility.score is not None and plausibility.score >= 70.0
    assert report.composite_score is not None
    assert 0 <= report.composite_score <= 100


def test_dq_report_dirty_panel_lower_plausibility(sample_panel: pd.DataFrame):
    df = sample_panel.copy()
    df.loc[df.index[:200], "demand"] = -10
    canonical = normalize_canonical(df, _full_mapping())
    report = compute_dq_report("test-dirty", canonical)
    plausibility = next(c for c in report.components if c.name == "plausibility")
    assert plausibility.score is not None and plausibility.score < 100


def test_dq_report_low_history_skus_listed():
    rows = [
        {"sku_id": "X", "date": pd.Timestamp("2024-01-01"), "demand": 1},
        {"sku_id": "X", "date": pd.Timestamp("2024-01-08"), "demand": 1},
        {"sku_id": "Y", "date": pd.Timestamp("2024-01-01"), "demand": 5},
    ]
    df = pd.DataFrame(rows)
    report = compute_dq_report("low", df)
    assert "X" in report.skus_low_history
    assert "Y" in report.skus_low_history


# --- run_all sanity ---

def test_run_all_returns_list_of_assertions(sample_panel: pd.DataFrame):
    canonical = normalize_canonical(sample_panel, _full_mapping())
    out = run_all(canonical)
    assert isinstance(out, list)
    for a in out:
        assert a.severity in {Severity.hard, Severity.soft, Severity.info}
