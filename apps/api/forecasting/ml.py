"""Global LightGBM forecaster — one model per dataset, all SKUs together.

Per-SKU LightGBM on <100 obs would severely overfit; a global model with `sku_id` as a
categorical feature shares signal across the panel and stays sane on small SKUs.

Features:
- Lagged demand (lag 1, 7, 28 — adapted for D/W/M frequency)
- Rolling means (window 4, 13)
- Calendar: day_of_week, week_of_year, month, US-holiday flag (from M5 calendar_effects.json
  if frequency == 'D'), is_year_end
- Categorical: sku_id, category, supplier (one-hot via LightGBM's native categorical handling)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from apps.api.forecasting.classical import QUANTILES
from apps.api.forecasting.schemas import Frequency

LAGS_BY_FREQUENCY: dict[Frequency, list[int]] = {
    "D": [1, 7, 14, 28],
    "W": [1, 4, 13, 26],
    "M": [1, 3, 6, 12],
}
ROLLING_BY_FREQUENCY: dict[Frequency, list[int]] = {
    "D": [7, 28],
    "W": [4, 13],
    "M": [3, 6],
}


@dataclass
class MLOutput:
    method: str
    point: np.ndarray
    quantiles: dict[float, np.ndarray]


def is_available() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except Exception:
        return False


def _add_calendar_features(df: pd.DataFrame, frequency: Frequency) -> pd.DataFrame:
    out = df.copy()
    out["dow"] = out["date"].dt.dayofweek.astype("int16")
    out["woy"] = out["date"].dt.isocalendar().week.astype("int16")
    out["month"] = out["date"].dt.month.astype("int16")
    out["is_month_end"] = out["date"].dt.is_month_end.astype("int8")
    out["is_year_end"] = out["date"].dt.is_year_end.astype("int8")
    return out


def _add_lag_features(df: pd.DataFrame, frequency: Frequency) -> pd.DataFrame:
    out = df.sort_values(["sku_id", "date"]).copy()
    g = out.groupby("sku_id", group_keys=False)
    for lag in LAGS_BY_FREQUENCY[frequency]:
        out[f"lag_{lag}"] = g["demand"].shift(lag)
    for w in ROLLING_BY_FREQUENCY[frequency]:
        out[f"rmean_{w}"] = g["demand"].transform(lambda s, w=w: s.shift(1).rolling(w, min_periods=2).mean())
    return out


def _add_llm_sku_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Join the 5-dim LLM-extracted SKU features onto the design matrix.

    The features are per-SKU (constant across time per SKU), so we materialize once via
    `features_for_panel` and merge. When no API key is set / lookup fails, every SKU gets
    the neutral fallback (all-zero / 0.5 essentials) — LightGBM treats it as a constant
    column and learns nothing from it, but doesn't break.

    Gated by env var so tests / batch jobs that don't want to pay the LLM cost can disable.
    """
    import os

    if os.environ.get("DISABLE_LLM_SKU_FEATURES") == "1":
        return df, []

    try:
        from apps.api.llm.sku_features import FEATURE_KEYS, features_for_panel
    except Exception:
        return df, []

    sku_to_features = features_for_panel(df[["sku_id", "category"]].drop_duplicates())
    if not sku_to_features:
        return df, []

    feat_rows = []
    for sku, f in sku_to_features.items():
        row = {"sku_id": sku}
        row.update(f.to_numeric_dict())
        feat_rows.append(row)
    if not feat_rows:
        return df, []
    feat_df = pd.DataFrame(feat_rows)
    # `sku_id` may already be a category dtype on df; convert temporarily to merge
    df_str = df.copy()
    df_str["sku_id"] = df_str["sku_id"].astype(str)
    merged = df_str.merge(feat_df, on="sku_id", how="left")
    # Fill NaN with neutral defaults (skus the LLM didn't label, e.g. beyond max_skus)
    for col in FEATURE_KEYS:
        if col in merged.columns:
            default = 0.5 if col == "discretionary_vs_essential" else 0.0
            merged[col] = merged[col].fillna(default).astype("float32")
    merged["sku_id"] = merged["sku_id"].astype("category")
    return merged, list(FEATURE_KEYS)


def _build_design_matrix(panel: pd.DataFrame, frequency: Frequency) -> tuple[pd.DataFrame, list[str], list[str]]:
    df = panel[["sku_id", "date", "demand", "category", "supplier"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = _add_calendar_features(df, frequency)
    df = _add_lag_features(df, frequency)
    df, llm_feature_cols = _add_llm_sku_features(df)

    cat_cols = ["sku_id", "category", "supplier"]
    for c in cat_cols:
        if c in df.columns:
            df[c] = df[c].astype("category")

    num_cols = (
        [f"lag_{l}" for l in LAGS_BY_FREQUENCY[frequency]]
        + [f"rmean_{w}" for w in ROLLING_BY_FREQUENCY[frequency]]
        + ["dow", "woy", "month", "is_month_end", "is_year_end"]
        + llm_feature_cols
    )
    feature_cols = num_cols + [c for c in cat_cols if c in df.columns]
    return df, feature_cols, [c for c in cat_cols if c in df.columns]


def train_global_model(panel: pd.DataFrame, frequency: Frequency, n_holdout: int = 8):
    """Train a single LightGBM model on the whole panel.

    Returns (model, feature_cols, val_score).
    """
    import lightgbm as lgb

    df, feature_cols, cat_cols = _build_design_matrix(panel, frequency)
    df = df.dropna(subset=[f"lag_{LAGS_BY_FREQUENCY[frequency][0]}"])
    if df.empty:
        raise ValueError("not enough history to train ML forecaster")

    df = df.sort_values("date")
    cutoff = df["date"].max() - pd.tseries.frequencies.to_offset({"D": "D", "W": "W", "M": "MS"}[frequency]) * n_holdout
    train = df[df["date"] <= cutoff]
    val = df[df["date"] > cutoff]
    if train.empty:
        train, val = df.iloc[: int(0.8 * len(df))], df.iloc[int(0.8 * len(df)):]

    train_set = lgb.Dataset(train[feature_cols], label=train["demand"], categorical_feature=cat_cols)
    val_set = lgb.Dataset(val[feature_cols], label=val["demand"], categorical_feature=cat_cols, reference=train_set)
    params = {
        "objective": "regression_l1",
        "metric": "mae",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 5,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 5,
        "verbose": -1,
        "deterministic": True,
        "force_row_wise": True,
    }
    model = lgb.train(
        params, train_set, num_boost_round=400,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )
    val_pred = model.predict(val[feature_cols])
    val_mae = float(np.mean(np.abs(val["demand"].to_numpy() - val_pred)))
    return model, feature_cols, cat_cols, val_mae


def forecast_ml(
    panel: pd.DataFrame,
    sku_id: str,
    horizon: int,
    frequency: Frequency,
    residual_std_for_intervals: float | None = None,
) -> MLOutput:
    """Train (or reuse) the global model and produce a multi-step forecast for one SKU.

    Multi-step strategy: recursive — predict step 1, append, recompute lag features, predict step 2, etc.
    Intervals: if `residual_std_for_intervals` is given, normal-approx around point.
    """
    from scipy.stats import norm

    model, feature_cols, cat_cols, val_mae = train_global_model(panel, frequency)
    sigma = residual_std_for_intervals if residual_std_for_intervals is not None else max(val_mae, 1e-3)

    history = panel[panel["sku_id"] == sku_id].sort_values("date").copy()
    if history.empty:
        raise ValueError(f"sku '{sku_id}' has no history in panel")

    points: list[float] = []
    period_offset = pd.tseries.frequencies.to_offset({"D": "D", "W": "W-MON", "M": "MS"}[frequency])
    last_date = history["date"].max()
    rolling = history.copy()

    for step in range(horizon):
        next_date = last_date + period_offset * (step + 1)
        new_row = {
            "sku_id": sku_id,
            "date": next_date,
            "demand": np.nan,
            "category": history["category"].iloc[-1] if "category" in history.columns else None,
            "supplier": history["supplier"].iloc[-1] if "supplier" in history.columns else None,
        }
        rolling = pd.concat([rolling, pd.DataFrame([new_row])], ignore_index=True)
        df, _, _ = _build_design_matrix(rolling, frequency)
        feat_row = df[df["date"] == pd.Timestamp(next_date)].iloc[-1:][feature_cols]
        if feat_row.isna().any().any():
            point = float(rolling["demand"].dropna().tail(8).mean() or 0.0)
        else:
            point = float(model.predict(feat_row)[0])
        point = max(0.0, point)
        points.append(point)
        rolling.loc[rolling.index[-1], "demand"] = point

    point_arr = np.array(points)
    quantiles: dict[float, np.ndarray] = {}
    for q in QUANTILES:
        z = float(norm.ppf(q))
        quantiles[q] = np.maximum(0.0, point_arr + z * sigma)

    return MLOutput(method="ml_lgb", point=point_arr, quantiles=quantiles)
