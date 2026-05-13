from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ForecastMethod = Literal[
    "ets", "arima", "seasonal_naive", "croston", "tsb",
    "ml_lgb", "chronos_bolt", "ensemble", "negbin_bayes",
]
Frequency = Literal["D", "W", "M"]
Pattern = Literal["smooth", "seasonal", "intermittent", "lumpy", "trending_new", "promo_driven"]
LeadTimeSource = Literal["observed", "category_default", "override"]


class ForecastDiagnostics(BaseModel):
    n_obs: int
    characterization: Pattern
    mape_backtest: float | None = None
    smape_backtest: float | None = None
    mase_backtest: float | None = None
    crps_backtest: float | None = None
    bias_backtest: float | None = None
    pinball_q95_backtest: float | None = None
    n_backtest_folds: int = 0
    prior_weight: float = 0.0


class ConformalCoverage(BaseModel):
    horizon: int = Field(description="Forecast steps ahead this coverage applies to (1-indexed).")
    nominal: float = Field(ge=0.0, le=1.0)
    empirical: float | None = Field(default=None, ge=0.0, le=1.0)
    n_residuals: int


class ForecastAudit(BaseModel):
    forecast_generated_at: datetime
    train_cutoff_date: str | None = None
    ensemble_weights: dict[str, float] = Field(default_factory=dict)
    ensemble_method_version: str = "v1"


class Forecast(BaseModel):
    sku_id: str
    method: ForecastMethod
    horizon_periods: int
    frequency: Frequency
    point: list[float]
    quantiles: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Keys are stringified quantile levels (e.g. '0.025', '0.5', '0.975').",
    )
    distribution_params: dict | None = None
    diagnostics: ForecastDiagnostics
    caveats: list[str] = []
    forecast_dates: list[str]
    conformal_coverage: list[ConformalCoverage] = Field(
        default_factory=list,
        description="Per-horizon empirical-vs-nominal coverage for the calibrated intervals.",
    )
    audit: ForecastAudit | None = None


class BacktestFold(BaseModel):
    fold_idx: int
    cutoff: str
    horizon: int
    mape: float | None = None
    smape: float | None = None
    mase: float | None = None
    crps: float | None = None
    bias: float | None = None
    pinball_q95: float | None = None


class BacktestResult(BaseModel):
    sku_id: str
    method: ForecastMethod
    n_folds: int
    folds: list[BacktestFold]
    mape: float | None = None
    smape: float | None = None
    mase: float | None = None
    crps: float | None = None
    bias: float | None = None
    pinball_q95: float | None = None
