"""Tests for the three deferred features: 3.1 LLMTime, 3.2 SKU features, 3.4 structured anomaly explainer.

All three are designed to fall back gracefully when no ANTHROPIC_API_KEY is set, so tests run
deterministically against the heuristic / cache paths. Live API behavior is exercised by the
eval harness, not unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.config import get_settings
from apps.api.main import app


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "datasets"
    data_dir.mkdir()
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def dataset_id(client: TestClient, sample_csv_bytes: bytes) -> str:
    up = client.post("/datasets/upload", files={"file": ("r.csv", sample_csv_bytes, "text/csv")})
    preview = up.json()
    mapping = {s["canonical"]: s["file_column"] for s in preview["suggested_mapping"] if s["file_column"]}
    client.post(f"/datasets/{preview['dataset_id']}/confirm", json=mapping)
    return preview["dataset_id"]


# ---------- 3.2 SKU features ----------


def test_sku_features_falls_back_to_neutral_without_api_key(monkeypatch: pytest.MonkeyPatch):
    from apps.api.llm.sku_features import FEATURE_KEYS, extract_features

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    out = extract_features("SKU-001", "FOODS_1", description="Milk - whole gallon")
    # Neutral: bools False (0.0), discretionary 0.5
    assert out.is_perishable == 0.0
    assert out.discretionary_vs_essential == 0.5
    assert out.source == "heuristic"
    # All 5 feature keys present in numeric view
    numeric = out.to_numeric_dict()
    assert set(numeric.keys()) == set(FEATURE_KEYS)


def test_sku_features_cache_key_shared_across_skus_with_same_description(monkeypatch: pytest.MonkeyPatch):
    """Two different SKU IDs with the same (category, description) hit the same cache key.
    This is intentional — most variant SKUs (color/size) share product semantics."""
    from apps.api.llm.sku_features import _cache_key

    a = _cache_key("FOODS_1", "Milk - whole gallon")
    b = _cache_key("FOODS_1", "Milk - whole gallon")
    c = _cache_key("FOODS_1", "Soda - cherry")
    assert a == b
    assert a != c


def test_sku_features_persists_to_cache(monkeypatch: pytest.MonkeyPatch):
    """After extract_features runs (even with heuristic fallback), the cache file exists so
    repeat calls don't re-trigger the LLM path."""
    from apps.api.llm.sku_features import _cache_key, _cache_path, extract_features

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    extract_features("SKU-X", "MISC", "test product")
    key = _cache_key("MISC", "test product")
    assert _cache_path(key).exists()


def test_features_for_panel_respects_max_skus(monkeypatch: pytest.MonkeyPatch):
    from apps.api.llm.sku_features import features_for_panel

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    panel = pd.DataFrame({
        "sku_id": [f"SKU-{i:03d}" for i in range(10)],
        "category": ["CAT_A"] * 5 + ["CAT_B"] * 5,
    })
    out = features_for_panel(panel, max_skus_to_label=5)
    assert len(out) == 5


def test_ml_design_matrix_includes_llm_features_when_enabled(monkeypatch: pytest.MonkeyPatch, dataset_id: str):
    """With DISABLE_LLM_SKU_FEATURES unset and no API key (so heuristic neutral applies), the
    design matrix should still gain the 5 numeric LLM columns."""
    from apps.api.forecasting.ml import _build_design_matrix

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.delenv("DISABLE_LLM_SKU_FEATURES", raising=False)

    from apps.api.db import open_dataset
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT sku_id, date, demand, category, supplier FROM panel").fetchdf()

    df, feature_cols, _cat_cols = _build_design_matrix(panel, "W")
    for col in ("is_perishable", "is_seasonal", "discretionary_vs_essential", "gift_likelihood", "weather_sensitive"):
        assert col in feature_cols, f"missing LLM feature column {col}"
        assert col in df.columns


def test_ml_design_matrix_drops_llm_features_when_flag_disabled(monkeypatch: pytest.MonkeyPatch, dataset_id: str):
    """DISABLE_LLM_SKU_FEATURES=1 must keep the matrix lean — no LLM columns appear."""
    from apps.api.forecasting.ml import _build_design_matrix

    monkeypatch.setenv("DISABLE_LLM_SKU_FEATURES", "1")

    from apps.api.db import open_dataset
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT sku_id, date, demand, category, supplier FROM panel").fetchdf()

    df, feature_cols, _ = _build_design_matrix(panel, "W")
    for col in ("is_perishable", "is_seasonal", "discretionary_vs_essential", "gift_likelihood", "weather_sensitive"):
        assert col not in feature_cols


# ---------- 3.4 Structured anomaly explainer ----------


def test_anomaly_explainer_returns_judgment_field_in_heuristic_path(monkeypatch: pytest.MonkeyPatch, dataset_id: str):
    """Without an API key, the explainer still returns a judgment dict — source=heuristic."""
    from apps.api.llm.anomaly_explainer import explain_anomaly_for_sku

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    # Pick a SKU that exists; even without an actual anomaly, the no-events branch returns
    # an explanation but judgment=None. So we exercise BOTH paths:
    from apps.api.db import open_dataset
    with open_dataset(dataset_id, read_only=True) as conn:
        sku = conn.execute("SELECT sku_id FROM panel LIMIT 1").fetchone()[0]

    out = explain_anomaly_for_sku(dataset_id, sku, severity_threshold=0.01)  # very low threshold → some events likely
    # The judgment field is present (either None when no events, or a dict with required keys)
    assert "judgment" in out
    if out["judgment"] is not None:
        assert set(out["judgment"].keys()) >= {"cause", "confidence", "evidence", "suggested_adjustment", "source"}
        assert out["judgment"]["source"] == "heuristic"


def test_anomaly_calendar_context_picks_up_christmas():
    """The calendar enricher tags Christmas as nearby for late-December events."""
    from apps.api.llm.anomaly_explainer import _calendar_context_near

    out = _calendar_context_near("2026-12-22")
    assert any("Christmas" in label for label in out), out


def test_submit_anomaly_explanation_rejects_invalid_cause(dataset_id: str):
    """The executor's validator is the wire that ensures structured fields are well-formed
    even when the LLM tries something weird."""
    from apps.api.llm.executors import ToolExecutionError, execute_tool

    with pytest.raises(ToolExecutionError):
        execute_tool("submit_anomaly_explanation", dataset_id, {
            "cause": "alien_invasion",  # not in enum
            "confidence": 0.5,
            "evidence": ["something"],
            "suggested_adjustment": "ignore",
        })


def test_submit_anomaly_explanation_rejects_out_of_range_confidence(dataset_id: str):
    from apps.api.llm.executors import ToolExecutionError, execute_tool

    with pytest.raises(ToolExecutionError):
        execute_tool("submit_anomaly_explanation", dataset_id, {
            "cause": "unclear",
            "confidence": 1.5,
            "evidence": ["x"],
            "suggested_adjustment": "investigate_manually",
        })


def test_submit_anomaly_explanation_happy_path(dataset_id: str):
    from apps.api.llm.executors import execute_tool

    out = execute_tool("submit_anomaly_explanation", dataset_id, {
        "cause": "holiday_or_calendar",
        "confidence": 0.7,
        "evidence": ["Christmas Eve falls within the spike window."],
        "suggested_adjustment": "ignore",
    })
    assert out["cause"] == "holiday_or_calendar"
    assert out["confidence"] == 0.7
    assert len(out["evidence"]) == 1


# ---------- 3.1 LLMTime forecaster ----------


def test_llm_forecaster_is_available_returns_false_without_flag(monkeypatch: pytest.MonkeyPatch):
    from apps.api.forecasting.llm_forecaster import is_available

    monkeypatch.delenv("ENABLE_LLM_FORECASTER", raising=False)
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    assert is_available() is False


def test_llm_forecaster_is_available_returns_false_without_api_key(monkeypatch: pytest.MonkeyPatch):
    from apps.api.forecasting.llm_forecaster import is_available

    monkeypatch.setenv("ENABLE_LLM_FORECASTER", "1")
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert is_available() is False


def test_llm_forecaster_is_available_true_when_both_set(monkeypatch: pytest.MonkeyPatch):
    from apps.api.forecasting.llm_forecaster import is_available

    monkeypatch.setenv("ENABLE_LLM_FORECASTER", "1")
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    assert is_available() is True


def test_llm_forecaster_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch):
    from apps.api.forecasting.llm_forecaster import forecast_llm

    monkeypatch.delenv("ENABLE_LLM_FORECASTER", raising=False)
    series = np.array([10.0, 12.0, 11.0, 13.0, 12.0, 14.0, 13.0, 15.0, 14.0, 16.0])
    out = forecast_llm(series, horizon=4)
    assert out is None


def test_llm_forecaster_returns_none_for_short_series(monkeypatch: pytest.MonkeyPatch):
    from apps.api.forecasting.llm_forecaster import forecast_llm

    monkeypatch.setenv("ENABLE_LLM_FORECASTER", "1")
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    out = forecast_llm(np.array([1.0, 2.0, 3.0]), horizon=4)
    assert out is None


def test_llm_forecaster_uses_cache_when_present(monkeypatch: pytest.MonkeyPatch):
    """Seed the cache with a known forecast; forecast_llm should return it without an API call."""
    from apps.api.forecasting.llm_forecaster import (
        _cache_path,
        _series_hash,
        forecast_llm,
    )

    monkeypatch.setenv("ENABLE_LLM_FORECASTER", "1")
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")  # not used because cache hits

    series = np.array([10.0, 12.0, 11.0, 13.0, 12.0, 14.0, 13.0, 15.0, 14.0, 16.0])
    horizon = 4
    key = _series_hash(series, horizon)
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"values": [20.0, 21.0, 22.0, 23.0]}))

    out = forecast_llm(series, horizon)
    assert out is not None
    assert out.method == "llm_time"
    assert list(out.point) == [20.0, 21.0, 22.0, 23.0]
    # quantiles populated for all standard levels
    for q in (0.025, 0.1, 0.5, 0.9, 0.975):
        assert q in out.quantiles
        assert len(out.quantiles[q]) == horizon


def test_llm_forecaster_norm_ppf_matches_scipy():
    """Acklam's approximation should be close to scipy on common quantile levels."""
    from apps.api.forecasting.llm_forecaster import _norm_ppf
    from scipy.stats import norm

    for q in (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975):
        approx = _norm_ppf(q)
        exact = float(norm.ppf(q))
        assert abs(approx - exact) < 1e-3, f"q={q}: approx={approx} exact={exact}"


def test_forecast_sku_does_not_break_when_llm_forecaster_disabled(monkeypatch: pytest.MonkeyPatch, dataset_id: str):
    """Default enable_llm_forecaster=False should leave forecast_sku output identical to before."""
    from apps.api.forecasting.forecast import forecast_sku
    from apps.api.db import open_dataset

    monkeypatch.delenv("ENABLE_LLM_FORECASTER", raising=False)
    with open_dataset(dataset_id, read_only=True) as conn:
        sku = conn.execute("SELECT sku_id FROM panel LIMIT 1").fetchone()[0]

    out = forecast_sku(dataset_id, sku, horizon=4, n_backtest_folds=2)
    assert out.sku_id == sku
    assert "llm_time" not in out.audit.ensemble_weights
