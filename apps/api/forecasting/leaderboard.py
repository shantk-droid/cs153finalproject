"""Per-SKU model leaderboard: backtest each available method, compare MAPE/CRPS.

Calls forecast_sku and reads the diagnostics from each method-disabled run to
build a per-method comparison table. Cached lightly to avoid recomputing on
every page load.
"""

from __future__ import annotations

from apps.api.forecasting.forecast import forecast_sku


METHODS_TO_TRY = [
    ("classical", "Classical (ETS/ARIMA/Croston/TSB)", {"enable_foundation": False, "enable_ml": False, "enable_ensemble": False}),
    ("ml_lgb", "LightGBM (global)", {"enable_foundation": False, "enable_ensemble": False}),
    ("chronos_bolt", "Chronos-Bolt", {"enable_ml": False, "enable_ensemble": False}),
    ("ensemble", "Ensemble (CRPS-weighted + conformal)", {}),
]


def compute_leaderboard(dataset_id: str, sku_id: str, horizon: int = 8) -> list[dict]:
    out: list[dict] = []
    selected_method: str | None = None
    best_crps = float("inf")

    for key, label, opts in METHODS_TO_TRY:
        try:
            f = forecast_sku(dataset_id, sku_id, horizon=horizon, n_backtest_folds=2, **opts)
        except Exception as e:
            out.append({
                "method": key,
                "available": False,
                "selected": False,
                "mape": None, "smape": None, "mase": None, "crps": None,
                "notes": f"unavailable: {type(e).__name__}: {e}"[:120],
            })
            continue
        d = f.diagnostics
        crps = d.crps_backtest if d.crps_backtest is not None else float("inf")
        if crps < best_crps:
            best_crps = crps
            selected_method = key
        out.append({
            "method": key,
            "available": True,
            "selected": False,
            "mape": d.mape_backtest,
            "smape": d.smape_backtest,
            "mase": d.mase_backtest,
            "crps": d.crps_backtest,
            "notes": f.method,
        })

    for r in out:
        if r["method"] == selected_method:
            r["selected"] = True
    return out
