"""Data Quality Score — composite 0–100 over five components.

Components:
- completeness, plausibility, history_depth          (always available)
- distribution_profile                               (soft-penalty match against the chosen profile)
- stationarity / regime_stability                    (Pettitt + MK + rolling shift)

Component scores are 0–100. Composite is the weighted average over components that have a score
(unavailable ones are skipped and the remaining weights renormalize).

The new (post-profile) weighting de-emphasises distribution_profile because it's contextual
("does this look like the kind of data we expect?") rather than diagnostic ("is your data
broken?"). Completeness and plausibility carry more weight as the real "is this dataset
usable" signals.
"""

from __future__ import annotations

import pandas as pd

from apps.api.assertions.business_logic import run_all as run_business_logic
from apps.api.assertions.schemas import (
    Assertion,
    ComponentScore,
    DataQualityReport,
    ProfileInfo,
    Severity,
)
from apps.api.assertions.stationarity import evaluate_panel as evaluate_stationarity, regime_break_skus
from apps.api.assertions.statistical import evaluate_panel as evaluate_distribution
from apps.api.ingestion.validators import infer_frequency
from apps.api.profiles import Profile, get_profile

DEFAULT_WEIGHTS: dict[str, float] = {
    "completeness":         0.25,
    "plausibility":         0.25,
    "history_depth":        0.20,
    "stationarity":         0.15,
    "distribution_profile": 0.15,
}

LOW_HISTORY_THRESHOLD = 13  # observations — below this we caveat forecasts


def _completeness_score(df: pd.DataFrame) -> tuple[float, list[str]]:
    """% of optional fields populated + % of expected dates covered per SKU."""
    notes: list[str] = []
    optional = ("on_hand", "lead_time_days", "unit_cost", "unit_price", "supplier", "category")
    populated = [c for c in optional if c in df.columns and df[c].notna().any()]
    presence = len(populated) / len(optional) if optional else 1.0

    coverage_components = []
    for sku, g in df.groupby("sku_id"):
        dates = g["date"].drop_duplicates().sort_values()
        if len(dates) < 2:
            continue
        diffs = dates.diff().dt.days.dropna()
        median = max(1.0, diffs.median())
        expected = (dates.max() - dates.min()).days / median + 1
        coverage_components.append(len(dates) / expected if expected > 0 else 1.0)
    coverage = sum(coverage_components) / len(coverage_components) if coverage_components else 1.0

    score = 100.0 * (0.4 * presence + 0.6 * min(1.0, coverage))
    notes.append(f"{len(populated)}/{len(optional)} optional fields populated")
    notes.append(f"{coverage:.1%} median date coverage per SKU")
    return round(score, 2), notes


def _plausibility_score(df: pd.DataFrame, business_assertions: list[Assertion]) -> tuple[float, list[str]]:
    """Penalize per business-logic violation, weighted by row count and SKU count."""
    n_rows = max(1, len(df))
    n_skus = max(1, df["sku_id"].nunique())
    soft = [a for a in business_assertions if a.severity == Severity.soft]
    if not soft:
        return 100.0, ["no business-logic warnings triggered"]
    notes: list[str] = []
    penalty = 0.0
    for a in soft:
        row_pct = a.offending_row_count / n_rows
        sku_pct = (a.skus_affected or 0) / n_skus if a.skus_affected else 0.0
        weight = max(row_pct, sku_pct)
        contribution = min(20.0, weight * 100.0)
        penalty += contribution
        notes.append(f"-{contribution:.1f} from {a.code} ({a.offending_row_count} rows, {a.skus_affected} SKUs)")
    score = max(0.0, 100.0 - penalty)
    return round(score, 2), notes


def _history_depth_score(df: pd.DataFrame) -> tuple[float, list[str], list[str]]:
    """Per-SKU obs count → score; aggregate via mean. Surface SKUs below threshold."""
    counts = df.groupby("sku_id").size()
    if counts.empty:
        return 0.0, ["no rows"], []
    median_n = float(counts.median())
    scores = counts.clip(upper=104).astype(float) / 104.0 * 100.0
    score = float(scores.mean())
    low_skus = counts[counts < LOW_HISTORY_THRESHOLD].index.tolist()
    notes = [
        f"median {median_n:.0f} observations per SKU",
        f"{len(low_skus)} SKUs have < {LOW_HISTORY_THRESHOLD} observations and will be flagged for cold-start treatment",
    ]
    return round(score, 2), notes, low_skus


def compute_dq_report(
    dataset_id: str,
    df: pd.DataFrame,
    profile_id: str = "retail_m5",
    schema_assertions: list[Assertion] | None = None,
    weights: dict[str, float] | None = None,
    profile_auto_detected: bool = False,
    profile_match_confidence: float | None = None,
) -> DataQualityReport:
    """Build the DataQualityReport for an ingested dataset.

    `profile_id` selects which reference profile bands to score against. If the dataset
    was uploaded with profile_id="auto", the caller is expected to resolve to a concrete
    id via `apps.api.profiles.match_profile` and pass `profile_auto_detected=True`.
    """
    schema_assertions = schema_assertions or []
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    profile: Profile = get_profile(profile_id)
    profile_info = ProfileInfo(
        profile_id=profile.id,
        label=profile.label,
        auto_detected=profile_auto_detected,
        match_confidence=profile_match_confidence,
    )

    business_assertions = run_business_logic(df)
    all_assertions = list(schema_assertions) + business_assertions

    completeness, completeness_notes = _completeness_score(df)
    plausibility, plausibility_notes = _plausibility_score(df, business_assertions)
    history, history_notes, low_history_skus = _history_depth_score(df)

    dist_score, dist_anomalies, dist_notes, flagged_metrics = evaluate_distribution(df, profile)
    extra_assertions: list[Assertion] = []
    if dist_anomalies:
        top_metrics = sorted(flagged_metrics.items(), key=lambda kv: -kv[1])[:3]
        message = (
            f"{len(dist_anomalies)} per-SKU metric values fall outside the typical band for "
            f"{profile.label}. This is informational. If your data is from a different domain, "
            f"change profile in Settings."
        )
        if top_metrics:
            message += " Top metrics: " + ", ".join(f"{k}={v}" for k, v in top_metrics if v)
        extra_assertions.append(Assertion(
            code="DISTRIBUTION_PROFILE_NOTE",
            severity=Severity.info,
            field=None,
            message=message,
            offending_examples=[{
                "sku_id": a.sku_id, "metric": a.metric, "value": round(a.value, 4),
                "profile_p10": round(a.profile_p10, 4), "profile_p90": round(a.profile_p90, 4),
                "side": a.side,
            } for a in dist_anomalies[:5]],
            offending_row_count=len(dist_anomalies),
            skus_affected=len({a.sku_id for a in dist_anomalies}),
        ))

    frequency = infer_frequency(df["date"]) or "W"
    stationarity_score, stationarity_flags = evaluate_stationarity(df, frequency)
    regime_skus = regime_break_skus(stationarity_flags)
    if regime_skus:
        extra_assertions.append(Assertion(
            code="REGIME_BREAK",
            severity=Severity.soft,
            field=None,
            message=(
                f"{len(regime_skus)} SKUs have a structural break in the recent window — "
                "forecasts on these SKUs will be caveated."
            ),
            offending_examples=[{
                "sku_id": f.sku_id,
                "stationarity_score": round(f.score, 1),
                "reason": f.reason,
            } for f in stationarity_flags if f.score < 70.0][:5],
            offending_row_count=len(regime_skus),
            skus_affected=len(regime_skus),
        ))

    components: list[ComponentScore] = [
        ComponentScore(name="completeness",         score=completeness, weight=w["completeness"], notes=completeness_notes),
        ComponentScore(name="plausibility",         score=plausibility, weight=w["plausibility"], notes=plausibility_notes),
        ComponentScore(name="distribution_profile", score=dist_score,    weight=w["distribution_profile"], notes=dist_notes),
        ComponentScore(name="history_depth",        score=history,       weight=w["history_depth"], notes=history_notes),
        ComponentScore(
            name="stationarity",
            score=stationarity_score,
            weight=w["stationarity"],
            notes=([f"{len(regime_skus)} SKUs with structural breaks (score < 70)"]
                   if stationarity_score is not None else
                   ["not enough recent history to test"]),
        ),
    ]

    available = [c for c in components if c.score is not None]
    if available:
        total_weight = sum(c.weight for c in available)
        composite = sum(c.score * c.weight for c in available) / total_weight if total_weight else None
        composite = round(composite, 2) if composite is not None else None
    else:
        composite = None

    skus_with_business_issues: set[str] = set()
    for a in business_assertions:
        for ex in a.offending_examples:
            sid = ex.get("sku_id")
            if isinstance(sid, str):
                skus_with_business_issues.add(sid)

    return DataQualityReport(
        dataset_id=dataset_id,
        composite_score=composite,
        components=components,
        assertions=all_assertions + extra_assertions,
        n_rows=len(df),
        n_skus=int(df["sku_id"].nunique()) if "sku_id" in df.columns else 0,
        skus_low_history=low_history_skus,
        skus_with_business_logic_issues=sorted(skus_with_business_issues),
        profile=profile_info,
        flagged_metrics={k: v for k, v in flagged_metrics.items() if v},
    )
