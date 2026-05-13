"""Runtime loader for M5 calibration artifacts. Cached, read-only.

Used by the forecasting layer (Bayes priors + pattern classifier) and the inventory layer
(category defaults).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from apps.api.config import get_settings
from apps.api.forecasting.bayes import GammaPrior


def _artifacts_dir() -> Path:
    return get_settings().m5_artifacts_path


@lru_cache(maxsize=1)
def calibration_version() -> str | None:
    p = _artifacts_dir() / "VERSION"
    return p.read_text().strip() if p.exists() else None


@lru_cache(maxsize=1)
def category_defaults() -> dict:
    p = _artifacts_dir() / "category_defaults.json"
    return json.loads(p.read_text()) if p.exists() else {}


@lru_cache(maxsize=1)
def series_priors() -> pd.DataFrame | None:
    p = _artifacts_dir() / "series_priors.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p)


@lru_cache(maxsize=1)
def dq_reference_dists() -> pd.DataFrame | None:
    p = _artifacts_dir() / "dq_reference_dists.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p)


@lru_cache(maxsize=1)
def pattern_classifier_meta() -> dict | None:
    p = _artifacts_dir() / "pattern_classifier_meta.json"
    return json.loads(p.read_text()) if p.exists() else None


@lru_cache(maxsize=1)
def pattern_classifier_model():
    """Lazy-load the LightGBM model. Returns None if libomp / lightgbm aren't available."""
    p = _artifacts_dir() / "pattern_classifier.lgb"
    if not p.exists():
        return None
    try:
        import lightgbm as lgb
        return lgb.Booster(model_file=str(p))
    except Exception:
        return None


def lookup_prior(category: str | None, pattern: str) -> GammaPrior:
    """Find the (dept, pattern) prior that best matches the user's category."""
    df = series_priors()
    if df is None or df.empty:
        return GammaPrior.default()

    candidates = df[df["pattern"] == pattern]
    if candidates.empty:
        candidates = df

    if category:
        cat_upper = category.upper()
        match = candidates[candidates["dept_id"].str.upper() == cat_upper]
        if not match.empty:
            row = match.iloc[0]
            return GammaPrior(alpha=float(row["alpha"]), beta=float(row["beta"]),
                              n_observed_skus=int(row["n_observed_skus"]),
                              source=f"m5:{row['dept_id']}:{pattern}")
        prefix = cat_upper.split("_")[0]
        prefix_match = candidates[candidates["dept_id"].str.upper().str.startswith(prefix)]
        if not prefix_match.empty:
            row = prefix_match.sort_values("n_observed_skus", ascending=False).iloc[0]
            return GammaPrior(alpha=float(row["alpha"]), beta=float(row["beta"]),
                              n_observed_skus=int(row["n_observed_skus"]),
                              source=f"m5:{row['dept_id']}:{pattern}:prefix")

    weighted = candidates.assign(
        weight=candidates["n_observed_skus"].astype(float),
    )
    total_w = float(weighted["weight"].sum())
    if total_w <= 0:
        return GammaPrior.default()
    alpha = float((weighted["alpha"] * weighted["weight"]).sum() / total_w)
    beta = float((weighted["beta"] * weighted["weight"]).sum() / total_w)
    return GammaPrior(alpha=alpha, beta=beta, n_observed_skus=int(total_w), source=f"m5:avg:{pattern}")
