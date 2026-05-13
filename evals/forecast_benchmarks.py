"""M5 holdout forecast benchmarks.

Run from repo root:
    python evals/forecast_benchmarks.py --raw data/raw --n-skus 100 --horizon 28

Reports per-method MAPE / sMAPE / CRPS / pinball_q95 across a sample of M5 SKUs at the
day level. Used to track regressions PR-to-PR. Day 8 (foundation + ensemble) should beat
the Day 3 classical baseline by ≥3% on CRPS.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from apps.api.forecasting.backtest import backtest_sku
from apps.api.forecasting.characterize import characterize_series
from apps.api.forecasting.classical import (
    QUANTILES,
    forecast_classical,
    history_dataframe,
)
from apps.api.forecasting.metrics import (
    crps_from_quantiles,
    mape,
    pinball_loss,
    smape,
)


def m5_to_long(sales_path: Path, calendar_path: Path, n_skus: int, seed: int) -> pd.DataFrame:
    sales = pd.read_csv(sales_path)
    calendar = pd.read_csv(calendar_path, parse_dates=["date"])

    rng = np.random.default_rng(seed)
    if n_skus < len(sales):
        idx = rng.choice(len(sales), size=n_skus, replace=False)
        sales = sales.iloc[idx].reset_index(drop=True)

    id_cols = ["id", "item_id", "dept_id", "cat_id", "store_id", "state_id"]
    day_cols = [c for c in sales.columns if c.startswith("d_")]
    d_to_date = dict(zip(calendar["d"], pd.to_datetime(calendar["date"])))

    long = sales.melt(id_vars=id_cols, value_vars=day_cols, var_name="d", value_name="demand")
    long["date"] = long["d"].map(d_to_date)
    long = long.drop(columns=["d"])
    long = long.rename(columns={"id": "sku_id"})
    return long[["sku_id", "date", "demand"]].sort_values(["sku_id", "date"]).reset_index(drop=True)


def evaluate_sku(g: pd.DataFrame, horizon: int) -> dict | None:
    """Train on all but last `horizon` days, forecast, score."""
    if len(g) < horizon + 30:
        return None
    train = g.iloc[:-horizon].reset_index(drop=True)
    test = g.iloc[-horizon:].reset_index(drop=True)

    pattern = characterize_series(train["demand"], "D")
    history = history_dataframe(g["sku_id"].iloc[0], train["date"], train["demand"])
    try:
        out = forecast_classical(history, horizon=horizon, frequency="D", pattern=pattern)
    except Exception as e:
        return {"sku_id": g["sku_id"].iloc[0], "error": str(e)}

    actual = test["demand"].to_numpy(dtype=float)
    q_levels = np.array(QUANTILES)
    q_values = np.column_stack([out.quantiles[q] for q in QUANTILES])

    return {
        "sku_id": g["sku_id"].iloc[0],
        "method": out.method,
        "pattern": pattern,
        "n_obs": int(len(train)),
        "mape": mape(actual, out.point),
        "smape": smape(actual, out.point),
        "crps": crps_from_quantiles(actual, q_levels, q_values),
        "pinball_q95": pinball_loss(actual, out.quantiles[0.975], 0.95),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M5 forecast benchmarks for v1 classical pipeline.")
    parser.add_argument("--raw", default="data/raw", help="Directory with M5 raw CSVs")
    parser.add_argument("--n-skus", type=int, default=100)
    parser.add_argument("--horizon", type=int, default=28)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default=None, help="Optional JSON output path")
    args = parser.parse_args()

    raw = Path(args.raw)
    print(f"Loading M5 from {raw} (n_skus={args.n_skus})")
    long = m5_to_long(raw / "sales_train_evaluation.csv", raw / "calendar.csv",
                      n_skus=args.n_skus, seed=args.seed)
    print(f"  long shape: {long.shape}")

    print(f"Forecasting last {args.horizon} days for each SKU...")
    t0 = time.time()
    results: list[dict] = []
    for i, (sku_id, g) in enumerate(long.groupby("sku_id"), start=1):
        r = evaluate_sku(g, args.horizon)
        if r:
            results.append(r)
        if i % 10 == 0:
            print(f"  {i}/{args.n_skus} ({time.time()-t0:.1f}s)")
    elapsed = time.time() - t0
    print(f"  done: {len(results)} SKUs scored in {elapsed:.1f}s ({elapsed/max(1,len(results)):.2f}s/SKU)")

    df = pd.DataFrame([r for r in results if "error" not in r])
    by_method = df.groupby("method").agg(
        n=("sku_id", "count"),
        mape=("mape", "mean"),
        smape=("smape", "mean"),
        crps=("crps", "mean"),
        pinball_q95=("pinball_q95", "mean"),
    ).round(3)
    print()
    print("Per method:")
    print(by_method.to_string())
    print()
    print(f"Overall: SKUs={len(df)}  MAPE={df['mape'].mean():.2f}  CRPS={df['crps'].mean():.3f}  pinball_q95={df['pinball_q95'].mean():.3f}")

    if args.out:
        Path(args.out).write_text(json.dumps({
            "n_skus": int(len(df)),
            "horizon_days": args.horizon,
            "elapsed_sec": elapsed,
            "by_method": by_method.reset_index().to_dict(orient="records"),
            "overall": {
                "mape": float(df["mape"].mean()),
                "smape": float(df["smape"].mean()),
                "crps": float(df["crps"].mean()),
                "pinball_q95": float(df["pinball_q95"].mean()),
            },
        }, indent=2))
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
