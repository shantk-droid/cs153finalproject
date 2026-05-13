from __future__ import annotations

from apps.api.forecasting.bayes import GammaPrior
from apps.api.m5 import loader


def test_calibration_version_is_stamped():
    v = loader.calibration_version()
    assert v is not None and len(v) > 5


def test_category_defaults_includes_default_fallback():
    d = loader.category_defaults()
    assert "_default" in d


def test_series_priors_loaded():
    df = loader.series_priors()
    assert df is not None
    assert {"dept_id", "pattern", "alpha", "beta", "n_observed_skus"}.issubset(df.columns)
    assert len(df) > 0


def test_lookup_prior_returns_valid_gamma_prior():
    p = loader.lookup_prior("FOODS_3", "smooth")
    assert isinstance(p, GammaPrior)
    assert p.alpha > 0 and p.beta > 0


def test_lookup_prior_falls_back_when_category_missing():
    p = loader.lookup_prior("NONEXISTENT_CATEGORY", "smooth")
    assert isinstance(p, GammaPrior)
    assert p.alpha > 0 and p.beta > 0


def test_pattern_classifier_loads():
    model = loader.pattern_classifier_model()
    assert model is not None
    meta = loader.pattern_classifier_meta()
    assert meta is not None
    assert "label_classes" in meta
    assert "feature_cols" in meta
