"""End-to-end forecast orchestration: load history → characterize → forecast → annotate.

Days 7+8 wiring:
- M5-trained pattern classifier with rule fallback (Day 7)
- Bayesian shrinkage cold-start branch when n_obs < threshold (Day 7)
- Multi-method ensemble: classical + Chronos-Bolt + global LightGBM (Day 8)
- CRPS-weighted combine + split-conformal interval calibration (Day 8)
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from apps.api.db import open_dataset
from apps.api.forecasting import foundation, llm_forecaster, ml
from apps.api.forecasting.backtest import backtest_sku
from apps.api.forecasting.bayes import (
    forecast_bayes_cold_start,
    prior_weight_fraction,
)
from apps.api.forecasting.characterize import characterize_with_classifier
from apps.api.forecasting.classical import (
    QUANTILES,
    forecast_classical,
    history_dataframe,
)
from apps.api.forecasting.conformal import (
    apply_conformal_to_quantiles,
    calibrate_residuals,
    residuals_from_backtest,
)
from apps.api.forecasting.ensemble import EnsembleMember, combine
from apps.api.forecasting.metrics import crps_from_quantiles
from apps.api.forecasting.schemas import (
    ConformalCoverage,
    Forecast,
    ForecastAudit,
    ForecastDiagnostics,
    Frequency,
)
from apps.api.ingestion.validators import infer_frequency
from apps.api.m5.loader import lookup_prior

MIN_OBS_FOR_FORECAST = 8
LOW_HISTORY_THRESHOLD = 13

BAYES_THRESHOLD: dict[Frequency, int] = {"D": 90, "W": 26, "M": 6}
MIN_FOUNDATION_OBS = 16
MIN_PANEL_SKUS_FOR_ML = 20
MIN_OBS_FOR_ML_TRAIN = 40


class ForecastError(ValueError):
    pass


def _load_sku_history(dataset_id: str, sku_id: str) -> pd.DataFrame:
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT date, demand FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id.strip().upper()],
        ).fetchdf()
    return df


def _detect_regime_break(demand: pd.Series, last_n: int = 30, prior_n: int = 60) -> str | None:
    arr = demand.to_numpy(dtype=float)
    if len(arr) < last_n + prior_n:
        return None
    last = arr[-last_n:]
    prior = arr[-(last_n + prior_n):-last_n]
    if prior.mean() <= 0:
        return None
    ratio = last.mean() / prior.mean()
    if ratio < 0.5 or ratio > 2.0:
        return f"recent {last_n}-period mean is {ratio:.2f}× prior {prior_n}-period mean"
    return None


def _collect_classical_residuals(
    df: pd.DataFrame,
    sku_id: str,
    frequency: Frequency,
    pattern,
    holdout_h: int,
    backtest_folds,
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """Refit classical at each backtest cutoff and collect (actual − point) residuals.

    Returns (flat_residuals, residuals_per_step). The flat array is the union across all
    horizon steps and folds (kept for backwards-compatible conformal width calibration).
    The dict is keyed by step-ahead (1-indexed) and holds per-step residuals across folds —
    used to surface per-horizon empirical coverage on the SKU page (h=1 vs h=4 etc.).
    """
    actuals: list[float] = []
    point_forecasts: list[float] = []
    per_step: dict[int, list[float]] = {}
    for fold in backtest_folds:
        cut_idx = df.index[df["date"] == pd.Timestamp(fold.cutoff)]
        if len(cut_idx) == 0:
            continue
        cut_pos = int(cut_idx[0])
        test_actual = df["demand"].iloc[cut_pos:cut_pos + holdout_h].to_numpy(dtype=float)
        if len(test_actual) == 0:
            continue
        history_train = history_dataframe(sku_id, df["date"].iloc[:cut_pos], df["demand"].iloc[:cut_pos])
        try:
            refit = forecast_classical(history_train, len(test_actual), frequency, pattern)
        except Exception:
            continue
        actuals.extend(test_actual.tolist())
        point_forecasts.extend(refit.point.tolist())
        for h_idx, (a, p) in enumerate(zip(test_actual, refit.point), start=1):
            per_step.setdefault(h_idx, []).append(float(a) - float(p))
    if len(actuals) < 2:
        return np.array([]), {}
    flat = residuals_from_backtest(np.array(actuals), np.array(point_forecasts))
    per_step_arr = {k: np.array(v, dtype=float) for k, v in per_step.items()}
    return flat, per_step_arr


def _per_horizon_coverage(
    per_step: dict[int, np.ndarray],
    horizons: tuple[int, ...] = (1, 4),
    levels: tuple[float, ...] = (0.95,),
) -> list[ConformalCoverage]:
    """For each (horizon, level), compute empirical coverage from the matching residuals."""
    out: list[ConformalCoverage] = []
    for h in horizons:
        residuals = per_step.get(h)
        if residuals is None or len(residuals) < 2:
            continue
        for level in levels:
            half = calibrate_residuals(residuals, level)
            empirical = float(np.mean(np.abs(residuals) <= half)) if half > 0 else None
            out.append(ConformalCoverage(
                horizon=h,
                nominal=level,
                empirical=empirical,
                n_residuals=int(len(residuals)),
            ))
    return out


def forecast_sku(
    dataset_id: str,
    sku_id: str,
    horizon: int = 12,
    n_backtest_folds: int = 3,
    enable_foundation: bool = True,
    enable_ml: bool = True,
    enable_ensemble: bool = True,
    enable_conformal: bool = True,
    enable_llm_forecaster: bool = False,
) -> Forecast:
    df = _load_sku_history(dataset_id, sku_id)
    if df.empty:
        raise ForecastError(f"sku '{sku_id}' has no history in dataset '{dataset_id}'")
    if len(df) < MIN_OBS_FOR_FORECAST:
        raise ForecastError(
            f"sku '{sku_id}' has only {len(df)} observations (need >= {MIN_OBS_FOR_FORECAST}). "
            "Refusing to forecast — accept low confidence explicitly to override."
        )

    frequency: Frequency | None = infer_frequency(df["date"])
    if frequency is None:
        raise ForecastError(f"could not infer frequency for sku '{sku_id}'")

    pattern, char_source = characterize_with_classifier(df["demand"], frequency)

    category = None
    with open_dataset(dataset_id, read_only=True) as conn:
        cat_row = conn.execute(
            "SELECT category FROM panel WHERE sku_id = ? AND category IS NOT NULL LIMIT 1",
            [sku_id.strip().upper()],
        ).fetchone()
        if cat_row:
            category = cat_row[0]

    backtest_horizon = min(horizon, max(2, len(df) // 5))
    backtest = backtest_sku(
        sku_id=sku_id, dates=df["date"], demand=df["demand"],
        frequency=frequency, horizon=backtest_horizon, n_folds=n_backtest_folds,
    )

    bayes_threshold = BAYES_THRESHOLD[frequency]
    use_bayes = len(df) < bayes_threshold

    caveats: list[str] = []
    method_label: str
    point_arr: np.ndarray
    quantiles_arr: dict[float, np.ndarray]
    prior_weight = 0.0
    ensemble_weights_out: dict[str, float] = {}
    conformal_coverage: list[ConformalCoverage] = []

    if use_bayes:
        prior = lookup_prior(category, pattern)
        bayes_out = forecast_bayes_cold_start(df["demand"].to_numpy(), prior, horizon)
        method_label = "negbin_bayes"
        point_arr = bayes_out.point
        quantiles_arr = bayes_out.quantiles
        prior_weight = prior_weight_fraction(prior, len(df))
        caveats.append(
            f"cold-start: {len(df)} observations < {bayes_threshold} → "
            f"Bayesian shrinkage applied (prior weight {prior_weight:.2f}, source: M5 {pattern})."
        )
    else:
        members: list[EnsembleMember] = []

        history = history_dataframe(sku_id, df["date"], df["demand"])
        classical_out = forecast_classical(history, horizon, frequency, pattern)
        members.append(EnsembleMember(
            method=classical_out.method,
            point=classical_out.point,
            quantiles=classical_out.quantiles,
            crps_backtest=backtest.crps,
        ))

        if enable_foundation and foundation.is_available() and len(df) >= MIN_FOUNDATION_OBS:
            try:
                holdout_h = backtest_horizon
                train_arr = df["demand"].iloc[:-holdout_h].to_numpy(dtype=float)
                test_arr = df["demand"].iloc[-holdout_h:].to_numpy(dtype=float)
                holdout = foundation.forecast_foundation(train_arr, holdout_h)
                q_grid = np.column_stack([holdout.quantiles[q] for q in QUANTILES])
                holdout_crps = float(crps_from_quantiles(test_arr, np.array(QUANTILES), q_grid))

                fwd = foundation.forecast_foundation(df["demand"].to_numpy(dtype=float), horizon)
                members.append(EnsembleMember(
                    method="chronos_bolt", point=fwd.point, quantiles=fwd.quantiles,
                    crps_backtest=holdout_crps,
                ))
            except Exception as e:
                caveats.append(f"foundation forecast skipped: {type(e).__name__}")

        if enable_ml and ml.is_available():
            with open_dataset(dataset_id, read_only=True) as conn:
                panel = conn.execute("SELECT sku_id, date, demand, category, supplier FROM panel").fetchdf()
            n_skus_panel = panel["sku_id"].nunique()
            if n_skus_panel >= MIN_PANEL_SKUS_FOR_ML and len(df) >= MIN_OBS_FOR_ML_TRAIN:
                try:
                    holdout_h = backtest_horizon
                    test_dates = df["date"].iloc[-holdout_h:]
                    panel_train = panel[
                        ~((panel["date"].isin(test_dates)) & (panel["sku_id"] == sku_id.strip().upper()))
                    ]
                    holdout = ml.forecast_ml(panel_train, sku_id.strip().upper(), holdout_h, frequency)
                    test_arr = df["demand"].iloc[-holdout_h:].to_numpy(dtype=float)
                    q_grid = np.column_stack([holdout.quantiles[q] for q in QUANTILES])
                    holdout_crps = float(crps_from_quantiles(test_arr, np.array(QUANTILES), q_grid))

                    fwd = ml.forecast_ml(panel, sku_id.strip().upper(), horizon, frequency)
                    members.append(EnsembleMember(
                        method="ml_lgb", point=fwd.point, quantiles=fwd.quantiles,
                        crps_backtest=holdout_crps,
                    ))
                except Exception as e:
                    caveats.append(f"ML forecast skipped: {type(e).__name__}")

        # LLMTime — in-context-learning forecaster (Gruver et al. 2023). Disabled by default;
        # turn on per-call via `enable_llm_forecaster=True` or globally via env. Cost ~$0.001
        # per series; cache makes repeat backtests cheap. Calibrated against the same holdout
        # as the other members so CRPS-weighting is comparable.
        if enable_llm_forecaster and llm_forecaster.is_available():
            try:
                holdout_h = backtest_horizon
                train_arr = df["demand"].iloc[:-holdout_h].to_numpy(dtype=float)
                test_arr = df["demand"].iloc[-holdout_h:].to_numpy(dtype=float)
                holdout_llm = llm_forecaster.forecast_llm(train_arr, holdout_h)
                if holdout_llm is not None:
                    q_grid = np.column_stack([holdout_llm.quantiles[q] for q in QUANTILES])
                    holdout_crps = float(crps_from_quantiles(test_arr, np.array(QUANTILES), q_grid))

                    fwd = llm_forecaster.forecast_llm(df["demand"].to_numpy(dtype=float), horizon)
                    if fwd is not None:
                        members.append(EnsembleMember(
                            method="llm_time",
                            point=fwd.point,
                            quantiles=fwd.quantiles,
                            crps_backtest=holdout_crps,
                        ))
            except Exception as e:
                caveats.append(f"LLMTime forecast skipped: {type(e).__name__}")

        if enable_ensemble and len(members) > 1:
            point_arr, quantiles_arr, ensemble_weights = combine(members)
            ensemble_weights_out = {m: float(w) for m, w in ensemble_weights.items() if w > 0}
            method_label = "ensemble"
            wstr = ", ".join(f"{m}={w:.2f}" for m, w in ensemble_weights_out.items())
            caveats.append(f"ensemble weights — {wstr}")
        else:
            chosen = members[0]
            point_arr, quantiles_arr = chosen.point, chosen.quantiles
            method_label = chosen.method
            ensemble_weights_out = {chosen.method: 1.0}

        if enable_conformal and backtest.n_folds > 0:
            resid, resid_per_step = _collect_classical_residuals(
                df=df, sku_id=sku_id, frequency=frequency, pattern=pattern,
                holdout_h=backtest_horizon, backtest_folds=backtest.folds,
            )
            if len(resid) >= 4:
                quantiles_arr, _ = apply_conformal_to_quantiles(
                    point=point_arr, quantiles=quantiles_arr, residuals=resid,
                )
            if resid_per_step:
                # Report empirical coverage at h={1, 4, 8, 12} so multi-period (s,S) schedules
                # planning out to h=12 have calibration data, not just the h=1/h=4 probe pair.
                # _per_horizon_coverage skips horizons that have no residuals, so passing all
                # four is safe even when backtest_horizon < 12.
                standard_horizons = tuple(h for h in (1, 4, 8, 12) if h in resid_per_step)
                if not standard_horizons:
                    standard_horizons = (max(resid_per_step.keys()),)
                conformal_coverage = _per_horizon_coverage(
                    resid_per_step,
                    horizons=standard_horizons,
                    levels=(0.80, 0.95),
                )

    if not use_bayes and len(df) < LOW_HISTORY_THRESHOLD:
        caveats.append(f"only {len(df)} observations — forecast is high-uncertainty.")
    if not use_bayes and pattern in ("intermittent", "lumpy") and method_label not in ("ensemble", "ml_lgb", "chronos_bolt"):
        caveats.append(
            "intermittent/lumpy demand — Croston-family methods produce point forecasts; "
            "intervals come from a normal residual approximation in v1."
        )
    if char_source == "rules_low_confidence":
        caveats.append("M5 classifier confidence below threshold; using hand rules.")
    regime = _detect_regime_break(df["demand"])
    if regime:
        caveats.append(f"regime break detected: {regime}")

    forecast_dates = pd.date_range(
        start=df["date"].max() + pd.tseries.frequencies.to_offset({"D": "D", "W": "W-MON", "M": "MS"}[frequency]),
        periods=horizon,
        freq={"D": "D", "W": "W-MON", "M": "MS"}[frequency],
    )

    audit = ForecastAudit(
        forecast_generated_at=datetime.now(timezone.utc),
        train_cutoff_date=df["date"].max().date().isoformat() if not df.empty else None,
        ensemble_weights=ensemble_weights_out,
        ensemble_method_version="v1",
    )

    return Forecast(
        sku_id=sku_id,
        method=method_label,  # type: ignore[arg-type]
        horizon_periods=horizon,
        frequency=frequency,
        point=[float(v) for v in point_arr],
        quantiles={str(q): [float(v) for v in quantiles_arr[q]] for q in QUANTILES},
        distribution_params=None,
        diagnostics=ForecastDiagnostics(
            n_obs=len(df),
            characterization=pattern,
            mape_backtest=backtest.mape,
            smape_backtest=backtest.smape,
            mase_backtest=backtest.mase,
            crps_backtest=backtest.crps,
            bias_backtest=backtest.bias,
            pinball_q95_backtest=backtest.pinball_q95,
            n_backtest_folds=backtest.n_folds,
            prior_weight=prior_weight,
        ),
        caveats=caveats,
        forecast_dates=[d.date().isoformat() for d in forecast_dates],
        conformal_coverage=conformal_coverage,
        audit=audit,
    )


def forecast_sku_summary(dataset_id: str, sku_id: str, horizon: int = 12) -> dict:
    f = forecast_sku(dataset_id, sku_id, horizon=horizon, n_backtest_folds=2,
                     enable_foundation=False, enable_ml=False, enable_ensemble=False)
    return {
        "sku_id": sku_id,
        "method": f.method,
        "horizon_total_demand": float(np.sum(f.point)),
        "mape_backtest": f.diagnostics.mape_backtest,
        "characterization": f.diagnostics.characterization,
        "n_obs": f.diagnostics.n_obs,
        "caveats": f.caveats,
    }
