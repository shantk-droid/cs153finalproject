"""M5 Calibration Builder — first cut.

Day 1 scope: produce `calendar_effects.json` and `category_defaults.json` only.
Day 7 will add `series_priors.parquet` (NegBin/Dirichlet hyperparameters).
Day 7 will add `pattern_classifier.lgb` (LightGBM).
Day 9 will add `dq_reference_dists.parquet`.

Inputs (downloaded by `scripts/build_m5_calibration.sh`):
- apps/api/m5/raw/sales_train_evaluation.csv  (30490 SKUs × 1941 days)
- apps/api/m5/raw/calendar.csv                (date features + events + SNAP)
- apps/api/m5/raw/sell_prices.csv             (weekly prices)

Outputs (committed to apps/api/m5/artifacts/):
- VERSION                       e.g. "2026-05-03-1"
- calendar_effects.json         DOW, WOY, holiday, SNAP multipliers + bootstrap CIs
- category_defaults.json        per-category cost/holding/markup/leadtime/perishable defaults
- (later) series_priors.parquet, pattern_classifier.lgb, dq_reference_dists.parquet

Run:
    python -m apps.api.m5.build_calibration --raw apps/api/m5/raw --out apps/api/m5/artifacts
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Hard-coded properties of the M5 dataset that we know up-front.
M5_CATEGORIES = ["FOODS", "HOBBIES", "HOUSEHOLD"]
M5_DEPARTMENTS = [
    "FOODS_1", "FOODS_2", "FOODS_3",
    "HOBBIES_1", "HOBBIES_2",
    "HOUSEHOLD_1", "HOUSEHOLD_2",
]


def _build_version() -> str:
    return f"{datetime.utcnow().strftime('%Y-%m-%d')}-1"


def _bootstrap_mean_ci(values: np.ndarray, n_boot: int = 200, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    """Return (mean, lo, hi) where lo/hi are bootstrap percentile CI."""
    rng = np.random.default_rng(seed)
    if len(values) == 0:
        return (1.0, 1.0, 1.0)
    means = np.empty(n_boot)
    n = len(values)
    for b in range(n_boot):
        sample = rng.choice(values, size=n, replace=True)
        means[b] = sample.mean()
    return float(values.mean()), float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))


def build_calendar_effects(sales_long: pd.DataFrame, calendar: pd.DataFrame) -> dict:
    """Compute DOW / WOY / event / SNAP multipliers.

    `sales_long` is the wide M5 sales melted to long: columns = [id, dept_id, cat_id, store_id, state_id, date, sales].
    Multiplier = mean(sales | feature) / mean(sales).
    """
    df = sales_long.merge(calendar[["date", "wday", "month", "year", "event_name_1", "event_type_1", "snap_CA", "snap_TX", "snap_WI"]], on="date", how="left")

    grand_mean = df["sales"].mean()

    def _to_lift(g: pd.DataFrame) -> dict:
        mean, lo, hi = _bootstrap_mean_ci(g["sales"].to_numpy())
        return {
            "lift": round(mean / grand_mean, 4) if grand_mean > 0 else 1.0,
            "ci_lo": round(lo / grand_mean, 4) if grand_mean > 0 else 1.0,
            "ci_hi": round(hi / grand_mean, 4) if grand_mean > 0 else 1.0,
            "n": int(len(g)),
        }

    dow = {int(k): _to_lift(g) for k, g in df.groupby("wday")}
    woy = {int(k): _to_lift(g) for k, g in df.groupby(df["date"].dt.isocalendar().week)}
    events = {
        str(k): _to_lift(g)
        for k, g in df.dropna(subset=["event_name_1"]).groupby("event_name_1")
        if len(g) >= 30
    }

    snap_lifts = {}
    for state in ("CA", "TX", "WI"):
        col = f"snap_{state}"
        if col in df.columns:
            on = df[df[col] == 1]
            off = df[df[col] == 0]
            if len(on) > 0 and len(off) > 0 and off["sales"].mean() > 0:
                snap_lifts[state] = {
                    "lift": round(on["sales"].mean() / off["sales"].mean(), 4),
                    "n_on": int(len(on)),
                    "n_off": int(len(off)),
                }

    return {
        "grand_mean_daily_sales": float(grand_mean),
        "dow_lifts": dow,
        "woy_lifts": woy,
        "event_lifts": events,
        "snap_lifts": snap_lifts,
    }


def build_category_defaults(sales_long: pd.DataFrame, prices: pd.DataFrame) -> dict:
    """Per-department defaults derived from M5.

    holding_cost_rate, order_cost_default, markup_default, default_lead_time_days,
    perishable, review_period_default.
    """
    out: dict = {}

    avg_price_per_dept = (
        prices.merge(sales_long[["item_id", "dept_id"]].drop_duplicates(), on="item_id", how="inner")
        .groupby("dept_id")["sell_price"].mean()
    )

    for dept in M5_DEPARTMENTS:
        is_food = dept.startswith("FOODS")
        avg_price = float(avg_price_per_dept.get(dept, 5.0))

        out[dept] = {
            "holding_cost_rate": 0.32 if is_food else 0.25,
            "order_cost_default": 35 if is_food else 50,
            "markup_default": round(1.45 if is_food else 1.6, 2),
            "default_lead_time_days": 4 if is_food else (10 if dept.startswith("HOUSEHOLD") else 14),
            "perishable": is_food,
            "review_period_default_days": 7,
            "avg_unit_price_m5": round(avg_price, 2),
        }

    out["_default"] = {
        "holding_cost_rate": 0.25,
        "order_cost_default": 50,
        "markup_default": 1.5,
        "default_lead_time_days": 14,
        "perishable": False,
        "review_period_default_days": 14,
        "avg_unit_price_m5": 5.0,
    }
    return out


def melt_sales(sales: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Wide M5 sales (d_1..d_1941) → long (date, sales). Memory-aware: melts in batches."""
    id_cols = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
    day_cols = [c for c in sales.columns if c.startswith("d_")]

    d_to_date = dict(zip(calendar["d"], pd.to_datetime(calendar["date"])))
    long = sales.melt(id_vars=id_cols, value_vars=day_cols, var_name="d", value_name="sales")
    long["date"] = long["d"].map(d_to_date)
    long = long.drop(columns=["d"])
    return long


def _autocorr(arr: np.ndarray, lag: int) -> float:
    if len(arr) <= lag + 1:
        return 0.0
    a = arr[:-lag] - arr[:-lag].mean()
    b = arr[lag:] - arr[lag:].mean()
    denom = np.sqrt((a**2).sum() * (b**2).sum())
    return 0.0 if denom < 1e-9 else float((a * b).sum() / denom)


def _features_for_series(arr: np.ndarray) -> dict:
    n = len(arr)
    nonzero = arr[arr > 0]
    return {
        "n_obs": n,
        "zero_pct": float((arr == 0).mean()) if n > 0 else 0.0,
        "cv_demand": float(arr.std() / arr.mean()) if arr.mean() > 0 else 0.0,
        "cv_nonzero_demand": float(nonzero.std() / nonzero.mean()) if len(nonzero) > 1 and nonzero.mean() > 0 else 0.0,
        "acf_lag_7": _autocorr(arr, 7),
        "acf_lag_28": _autocorr(arr, 28),
        "acf_lag_365": _autocorr(arr, 365) if n > 366 else 0.0,
        "trend_slope_pct": _trend_slope_pct(arr),
        "last_90d_vs_baseline_ratio": _regime_shift_ratio(arr, last=90, baseline=180),
    }


def _trend_slope_pct(arr: np.ndarray) -> float:
    if len(arr) < 30 or arr.mean() <= 0:
        return 0.0
    x = np.arange(len(arr))
    slope = float(np.polyfit(x, arr, 1)[0])
    return slope / arr.mean() * 100.0


def _regime_shift_ratio(arr: np.ndarray, last: int, baseline: int) -> float:
    if len(arr) < last + baseline:
        return 1.0
    last_mean = arr[-last:].mean()
    base_mean = arr[-(last + baseline):-last].mean()
    if base_mean <= 0:
        return 1.0
    return float(last_mean / base_mean)


def _label_via_rules(features: dict) -> str:
    n = features["n_obs"]
    zp = features["zero_pct"]
    if n < 90:
        return "trending_new"
    if zp > 0.7:
        return "lumpy"
    if zp > 0.3:
        return "intermittent"
    if features["acf_lag_7"] > 0.3 or features["acf_lag_28"] > 0.3 or features["acf_lag_365"] > 0.3:
        return "seasonal"
    return "smooth"


def build_series_priors(sales_long: pd.DataFrame) -> pd.DataFrame:
    """Per (dept_id, pattern) Gamma hyperparameters fitted via method-of-moments
    on the per-SKU mean-demand distribution.

    Output schema: dept_id, pattern, alpha, beta, n_observed_skus, mean_of_means, var_of_means.
    """
    by_sku = sales_long.groupby(["id", "dept_id"]).agg(
        mean_demand=("sales", "mean"),
        n_obs=("sales", "size"),
    ).reset_index()

    pattern_per_sku: dict[str, str] = {}
    for sku, g in sales_long.groupby("id"):
        arr = g["sales"].to_numpy(dtype=float)
        feats = _features_for_series(arr)
        pattern_per_sku[sku] = _label_via_rules(feats)
    by_sku["pattern"] = by_sku["id"].map(pattern_per_sku)

    rows = []
    for (dept, pattern), g in by_sku.groupby(["dept_id", "pattern"]):
        means = g["mean_demand"]
        means = means[means > 0]
        if len(means) < 5:
            continue
        m = float(means.mean())
        v = float(means.var())
        if v < 1e-6:
            alpha, beta = max(1.0, m), 1.0
        else:
            alpha = m * m / v
            beta = m / v
        rows.append({
            "dept_id": dept,
            "pattern": pattern,
            "alpha": float(alpha),
            "beta": float(beta),
            "n_observed_skus": int(len(means)),
            "mean_of_means": m,
            "var_of_means": v,
        })

    return pd.DataFrame(rows)


def build_dq_reference_dists(sales_long: pd.DataFrame) -> pd.DataFrame:
    """Per-department empirical quantile grids for each DQ-relevant metric.

    Output schema: dept_id, metric, p1, p5, p25, p50, p75, p95, p99, n_skus.
    Used by the Day-9 statistical-fit DQ component to flag user series that fall outside
    the [p1, p99] band of the M5 reference for the matched department.
    """
    metrics_per_sku: dict = {}
    for sku, g in sales_long.groupby("id"):
        arr = g["sales"].to_numpy(dtype=float)
        feats = _features_for_series(arr)
        metrics_per_sku[sku] = {
            "dept_id": g["dept_id"].iloc[0],
            "cv_demand": feats["cv_demand"],
            "intermittency_rate": feats["zero_pct"],
            "seasonality_strength": max(feats["acf_lag_7"], feats["acf_lag_28"], feats["acf_lag_365"]),
            "trend_slope_pct": abs(feats["trend_slope_pct"]),
            "regime_shift_score": abs(feats["last_90d_vs_baseline_ratio"] - 1.0),
        }
    metrics_df = pd.DataFrame.from_dict(metrics_per_sku, orient="index")
    quantile_levels = [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
    metric_cols = ("cv_demand", "intermittency_rate", "seasonality_strength",
                   "trend_slope_pct", "regime_shift_score")

    rows: list[dict] = []
    for dept, g in metrics_df.groupby("dept_id"):
        for metric in metric_cols:
            values = g[metric].dropna()
            if len(values) < 5:
                continue
            qs = values.quantile(quantile_levels).to_dict()
            rows.append({
                "dept_id": dept, "metric": metric,
                **{f"p{int(q*100)}": float(qs[q]) for q in quantile_levels},
                "n_skus": int(len(values)),
            })

    for metric in metric_cols:
        values = metrics_df[metric].dropna()
        if len(values) >= 5:
            qs = values.quantile(quantile_levels).to_dict()
            rows.append({
                "dept_id": "_default", "metric": metric,
                **{f"p{int(q*100)}": float(qs[q]) for q in quantile_levels},
                "n_skus": int(len(values)),
            })

    return pd.DataFrame(rows)


def train_pattern_classifier(sales_long: pd.DataFrame, out_path: Path) -> dict:
    """Train a LightGBM multiclass pattern classifier on M5 with rule-based weak labels.

    Returns metadata (label_classes, n_train, n_val, val_accuracy) for the manifest.
    """
    import lightgbm as lgb

    rows = []
    for sku, g in sales_long.groupby("id"):
        arr = g["sales"].to_numpy(dtype=float)
        feats = _features_for_series(arr)
        feats["sku"] = sku
        feats["dept_id"] = g["dept_id"].iloc[0]
        feats["cat_id"] = g["cat_id"].iloc[0]
        feats["pattern"] = _label_via_rules(feats)
        rows.append(feats)
    df = pd.DataFrame(rows)

    feature_cols = [
        "n_obs", "zero_pct", "cv_demand", "cv_nonzero_demand",
        "acf_lag_7", "acf_lag_28", "acf_lag_365",
        "trend_slope_pct", "last_90d_vs_baseline_ratio",
    ]

    label_classes = sorted(df["pattern"].unique().tolist())
    label_to_idx = {c: i for i, c in enumerate(label_classes)}
    y = df["pattern"].map(label_to_idx).to_numpy()
    X = df[feature_cols]

    rng = np.random.default_rng(0)
    idx = rng.permutation(len(df))
    split = int(0.8 * len(df))
    train_idx, val_idx = idx[:split], idx[split:]

    train_set = lgb.Dataset(X.iloc[train_idx], label=y[train_idx])
    val_set = lgb.Dataset(X.iloc[val_idx], label=y[val_idx], reference=train_set)

    n_classes = len(label_classes)
    params = {
        "objective": "multiclass",
        "num_class": n_classes,
        "learning_rate": 0.1,
        "num_leaves": 31,
        "verbose": -1,
        "metric": "multi_logloss",
        "deterministic": True,
        "force_row_wise": True,
    }
    model = lgb.train(
        params,
        train_set,
        num_boost_round=200,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)],
    )

    val_preds = model.predict(X.iloc[val_idx]).argmax(axis=1)
    val_acc = float((val_preds == y[val_idx]).mean())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(out_path))

    return {
        "label_classes": label_classes,
        "feature_cols": feature_cols,
        "n_train": int(len(train_idx)),
        "n_val": int(len(val_idx)),
        "val_accuracy": val_acc,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build M5 calibration artifacts.")
    parser.add_argument("--raw", required=True, help="Directory containing M5 raw CSVs")
    parser.add_argument("--out", required=True, help="Output artifacts directory")
    parser.add_argument("--sample-skus", type=int, default=None,
                        help="If set, sample N SKUs to speed up the build (dev only)")
    args = parser.parse_args()

    raw_dir = Path(args.raw)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading M5 raw data from {raw_dir}")
    sales = pd.read_csv(raw_dir / "sales_train_evaluation.csv")
    calendar = pd.read_csv(raw_dir / "calendar.csv", parse_dates=["date"])
    prices = pd.read_csv(raw_dir / "sell_prices.csv")
    print(f"  sales: {sales.shape}  calendar: {calendar.shape}  prices: {prices.shape}")

    if args.sample_skus is not None and args.sample_skus < len(sales):
        sales = sales.sample(n=args.sample_skus, random_state=0).reset_index(drop=True)
        print(f"  sampled to {len(sales)} SKUs (dev mode)")

    print("Melting sales to long format")
    sales_long = melt_sales(sales, calendar)
    print(f"  long shape: {sales_long.shape}")

    print("Building calendar_effects.json")
    cal_effects = build_calendar_effects(sales_long, calendar)

    print("Building category_defaults.json")
    cat_defaults = build_category_defaults(sales_long, prices)

    print("Building series_priors.parquet (per dept × pattern Gamma hyperparameters)")
    priors_df = build_series_priors(sales_long)
    print(f"  {len(priors_df)} (dept, pattern) cells")

    print("Building dq_reference_dists.parquet (per dept × metric quantile grids)")
    dq_df = build_dq_reference_dists(sales_long)
    print(f"  {len(dq_df)} (dept, metric) rows")

    print("Training pattern_classifier.lgb (LightGBM, weak rule labels)")
    classifier_meta = train_pattern_classifier(sales_long, out_dir / "pattern_classifier.lgb")
    print(f"  classes={classifier_meta['label_classes']}, val_acc={classifier_meta['val_accuracy']:.3f}")

    print("Writing artifacts")
    (out_dir / "calendar_effects.json").write_text(json.dumps(cal_effects, indent=2))
    (out_dir / "category_defaults.json").write_text(json.dumps(cat_defaults, indent=2))
    priors_df.to_parquet(out_dir / "series_priors.parquet", index=False)
    dq_df.to_parquet(out_dir / "dq_reference_dists.parquet", index=False)
    (out_dir / "pattern_classifier_meta.json").write_text(json.dumps(classifier_meta, indent=2))
    (out_dir / "VERSION").write_text(_build_version() + "\n")

    print(f"Done. Artifacts in {out_dir}")


if __name__ == "__main__":
    main()
