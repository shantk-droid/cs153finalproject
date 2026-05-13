"""Rolling-origin backtest harness.

For each fold we cut the series at increasing positions, fit the model, forecast `horizon`
steps, and compare against the held-out actuals. Returns per-fold + aggregate metrics.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.forecasting.characterize import characterize_series
from apps.api.forecasting.classical import (
    QUANTILES,
    forecast_classical,
    history_dataframe,
)
from apps.api.forecasting.metrics import (
    bias,
    crps_from_quantiles,
    mape,
    mase,
    pinball_loss,
    smape,
)
from apps.api.forecasting.schemas import (
    BacktestFold,
    BacktestResult,
    Frequency,
    ForecastMethod,
)


def rolling_origin_cutoffs(n: int, n_folds: int, horizon: int) -> list[int]:
    """Return cutoff indices spaced so each fold has `horizon` steps to score against."""
    if n - horizon < 8:
        return []
    last = n - horizon
    first = max(8, last - (n_folds - 1) * horizon)
    if last <= first:
        return [last]
    step = max(1, (last - first) // max(1, n_folds - 1))
    return list(range(first, last + 1, step))[:n_folds]


def backtest_sku(
    sku_id: str,
    dates: pd.Series,
    demand: pd.Series,
    frequency: Frequency,
    horizon: int = 4,
    n_folds: int = 4,
    season_m: int | None = None,
) -> BacktestResult:
    dates = pd.to_datetime(dates).reset_index(drop=True)
    demand = pd.to_numeric(demand).reset_index(drop=True)
    n = len(dates)

    cutoffs = rolling_origin_cutoffs(n, n_folds, horizon)
    if not cutoffs:
        return BacktestResult(
            sku_id=sku_id, method="seasonal_naive",
            n_folds=0, folds=[],
        )

    fold_results: list[BacktestFold] = []
    method_used: ForecastMethod = "seasonal_naive"
    for i, cut in enumerate(cutoffs):
        train_dates = dates.iloc[:cut]
        train_demand = demand.iloc[:cut]
        actual = demand.iloc[cut:cut + horizon].to_numpy()

        pattern = characterize_series(train_demand, frequency)
        history = history_dataframe(sku_id, train_dates, train_demand)
        try:
            out = forecast_classical(history, horizon, frequency, pattern)
        except Exception:
            continue
        method_used = out.method

        q_levels = np.array(QUANTILES)
        q_values = np.column_stack([out.quantiles[q] for q in QUANTILES])

        fold = BacktestFold(
            fold_idx=i,
            cutoff=str(dates.iloc[cut].date()),
            horizon=horizon,
            mape=_safe(mape(actual, out.point)),
            smape=_safe(smape(actual, out.point)),
            mase=_safe(mase(actual, out.point, train_demand.to_numpy(), season_m=season_m or 1)),
            crps=_safe(crps_from_quantiles(actual, q_levels, q_values)),
            bias=_safe(bias(actual, out.point)),
            pinball_q95=_safe(pinball_loss(actual, out.quantiles[0.975], 0.95)),
        )
        fold_results.append(fold)

    return BacktestResult(
        sku_id=sku_id,
        method=method_used,
        n_folds=len(fold_results),
        folds=fold_results,
        mape=_agg(fold_results, "mape"),
        smape=_agg(fold_results, "smape"),
        mase=_agg(fold_results, "mase"),
        crps=_agg(fold_results, "crps"),
        bias=_agg(fold_results, "bias"),
        pinball_q95=_agg(fold_results, "pinball_q95"),
    )


def _safe(v: float | None) -> float | None:
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return float(v)


def _agg(folds: list[BacktestFold], field: str) -> float | None:
    vals = [getattr(f, field) for f in folds if getattr(f, field) is not None]
    if not vals:
        return None
    return float(np.mean(vals))
