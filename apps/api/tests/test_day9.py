"""Day-9 tests: statistical fit + stationarity + LLM explainer (dry-run path)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.assertions.statistical import evaluate_panel as evaluate_distribution, metrics_for_sku
from apps.api.assertions.stationarity import (
    StationarityFlag,
    evaluate_panel as evaluate_stationarity,
    regime_break_skus,
)
from apps.api.profiles import get_profile


# --- distribution-profile ---

def test_metrics_for_sku_returns_5_keys():
    arr = np.array([1.0, 0, 2, 0, 3, 0, 4, 5, 6, 7, 8, 9])
    m = metrics_for_sku(arr)
    assert set(m.keys()) == {"cv_demand", "intermittency_rate", "seasonality_strength", "trend_slope_pct", "regime_shift_score"}


def test_evaluate_distribution_returns_none_when_no_evaluable_skus():
    panel = pd.DataFrame({"sku_id": ["X"]*5, "demand": [10.0]*5, "category": ["FOODS_3"]*5})
    score, anomalies, notes, flagged = evaluate_distribution(panel, get_profile("retail_m5"))
    assert score is None


def test_evaluate_distribution_against_retail_profile(sample_panel: pd.DataFrame):
    panel = sample_panel.copy()
    panel["category"] = "FOODS_3"
    score, anomalies, notes, flagged = evaluate_distribution(panel, get_profile("retail_m5"))
    assert score is not None
    assert 0.0 <= score <= 100.0


# --- stationarity ---

def test_stationarity_clean_series_high_score():
    rng = np.random.default_rng(0)
    rows = []
    for sku in ["X", "Y"]:
        for i in range(120):
            rows.append({
                "sku_id": sku,
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=i),
                "demand": 50 + rng.normal(0, 1),
            })
    panel = pd.DataFrame(rows)
    score, flags = evaluate_stationarity(panel, "W")
    assert score is not None and score > 70
    assert all(f.score >= 70 for f in flags)


def test_stationarity_regime_break_low_score():
    """A series whose recent window itself contains a step-change should fire at least
    one of the three detectors (Pettitt / MK / rolling-shift z-score).

    Window for weekly frequency = last + baseline = 4 + 13 = 17 weeks. The break needs to
    sit inside that window for the detectors to see it.
    """
    rng = np.random.default_rng(0)
    rows = []
    for i in range(40):
        rows.append({"sku_id": "X", "date": pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=i),
                     "demand": 10.0 + rng.normal(0, 0.5)})
    # Last 17 weeks: 13 stable + 4 jumped — break sits exactly at the window boundary
    for i in range(40, 53):
        rows.append({"sku_id": "X", "date": pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=i),
                     "demand": 10.0 + rng.normal(0, 0.5)})
    for i in range(53, 57):
        rows.append({"sku_id": "X", "date": pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=i),
                     "demand": 1000.0 + rng.normal(0, 5)})
    panel = pd.DataFrame(rows)
    score, flags = evaluate_stationarity(panel, "W")
    assert score is not None
    flag = flags[0]
    assert flag.score < 100.0
    assert flag.reason is not None
    assert flag.shift_zscore is not None and flag.shift_zscore > 2.0


# --- explainer dry-run (no API key needed for this path) ---

def test_explainer_falls_back_when_no_api_key(monkeypatch):
    from apps.api.assertions import explainer
    from apps.api.assertions.schemas import Assertion, ComponentScore, DataQualityReport, Severity

    class _NoKeySettings:
        anthropic_api_key = ""
        anthropic_model = "claude-sonnet-4-6"
        @property
        def data_path(self):
            from pathlib import Path
            import tempfile
            return Path(tempfile.mkdtemp())

    monkeypatch.setattr(explainer, "get_settings", lambda: _NoKeySettings())

    report = DataQualityReport(
        dataset_id="dummy",
        composite_score=75.0,
        components=[ComponentScore(name="completeness", score=80.0, weight=0.2)],
        assertions=[
            Assertion(code="X", severity=Severity.soft, field=None, message="msg X",
                      offending_examples=[], offending_row_count=1, skus_affected=1),
        ],
        n_rows=10, n_skus=1,
    )
    out = explainer.explain_top_issues(report, use_cache=False)
    assert out == {"X": "msg X"}
