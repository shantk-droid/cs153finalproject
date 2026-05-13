"""Python implementations of every tool exposed to Claude.

Each executor takes a `dataset_id` (scoped from the route) plus the raw `arguments` dict the
LLM emits, and returns a JSON-serializable result. We never reflect arbitrary kwargs into
existing functions — each executor extracts named fields explicitly so a hallucinated argument
doesn't crash anything.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from apps.api.db import dataset_path, open_dataset
from apps.api.forecasting.forecast import ForecastError, forecast_sku
from apps.api.ingestion.validators import infer_frequency
from apps.api.inventory.abc_xyz import classify_abc_xyz, heatmap_counts
from apps.api.inventory.recommend import recommend_sku
from apps.api.inventory.schemas import RecommendationOverrides


class ToolExecutionError(Exception):
    pass


def _require_dataset(dataset_id: str) -> None:
    if not dataset_path(dataset_id).exists():
        raise ToolExecutionError(f"dataset '{dataset_id}' not found")


# ---------- query_skus ----------

def _query_skus(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel").fetchdf()
    if panel.empty:
        return {"skus": [], "total_matched": 0}

    frequency = infer_frequency(panel["date"]) or "W"
    annualization = {"D": 365, "W": 52, "M": 12}[frequency]
    assignments = {a.sku_id: a for a in classify_abc_xyz(panel, annualization_factor=annualization)}

    last = panel.sort_values("date").groupby("sku_id").tail(1).set_index("sku_id")
    n_obs = panel.groupby("sku_id").size()

    rows = []
    for sku, row in last.iterrows():
        a = assignments.get(sku)
        if not a:
            continue
        if (cat := args.get("category")) and row.get("category") != cat:
            continue
        if (sup := args.get("supplier")) and row.get("supplier") != sup:
            continue
        if (abc := args.get("abc")) and a.abc != abc:
            continue
        if (xyz := args.get("xyz")) and a.xyz != xyz:
            continue
        rows.append({
            "sku_id": str(sku),
            "category": row.get("category"),
            "supplier": row.get("supplier"),
            "abc_class": a.abc,
            "xyz_class": a.xyz,
            "last_demand": float(row["demand"]) if pd.notna(row["demand"]) else 0.0,
            "on_hand": float(row["on_hand"]) if pd.notna(row.get("on_hand")) else None,
            "cv_demand": round(a.cv_demand, 3),
            "revenue_annual": round(a.revenue_annual, 2),
            "n_obs": int(n_obs.get(sku, 0)),
        })

    sort_by = args.get("sort_by", "revenue_annual")
    sort_dir = args.get("sort_dir", "desc")
    rows.sort(key=lambda r: r.get(sort_by) or 0, reverse=(sort_dir == "desc"))

    limit = int(args.get("limit", 25))
    return {"skus": rows[:limit], "total_matched": len(rows)}


# ---------- get_sku_details ----------

def _get_sku_details(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    sku_id = str(args.get("sku_id", "")).strip().upper()
    if not sku_id:
        raise ToolExecutionError("sku_id is required")
    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT * FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id],
        ).fetchdf()
        panel = conn.execute("SELECT * FROM panel").fetchdf()
    if df.empty:
        raise ToolExecutionError(f"sku '{sku_id}' not in dataset")

    frequency = infer_frequency(panel["date"]) or "W"
    annualization = {"D": 365, "W": 52, "M": 12}[frequency]
    assignments = {a.sku_id: a for a in classify_abc_xyz(panel, annualization_factor=annualization)}
    a = assignments.get(sku_id)

    last = df.iloc[-1]
    return {
        "sku_id": sku_id,
        "category": str(last["category"]) if pd.notna(last.get("category")) else None,
        "supplier": str(last["supplier"]) if pd.notna(last.get("supplier")) else None,
        "n_observations": int(len(df)),
        "date_min": str(df["date"].min().date()),
        "date_max": str(df["date"].max().date()),
        "frequency": frequency,
        "last_demand": float(last["demand"]),
        "mean_demand": float(df["demand"].mean()),
        "cv_demand": round(a.cv_demand, 3) if a else None,
        "abc_class": a.abc if a else "C",
        "xyz_class": a.xyz if a else "Z",
        "revenue_annual": round(a.revenue_annual, 2) if a else 0.0,
        "on_hand": float(last["on_hand"]) if pd.notna(last.get("on_hand")) else None,
        "unit_cost": float(df["unit_cost"].dropna().mean()) if df["unit_cost"].notna().any() else None,
        "unit_price": float(df["unit_price"].dropna().mean()) if df["unit_price"].notna().any() else None,
        "lead_time_days": float(df["lead_time_days"].dropna().mean()) if df["lead_time_days"].notna().any() else None,
    }


# ---------- get_forecast ----------

def _get_forecast(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    sku_id = str(args.get("sku_id", "")).strip().upper()
    horizon = int(args.get("horizon_periods", 12))
    if not sku_id:
        raise ToolExecutionError("sku_id is required")
    try:
        f = forecast_sku(dataset_id, sku_id, horizon=horizon, n_backtest_folds=2)
    except ForecastError as e:
        raise ToolExecutionError(str(e)) from e
    return {
        "sku_id": f.sku_id,
        "method": f.method,
        "horizon_periods": f.horizon_periods,
        "frequency": f.frequency,
        "point": [round(v, 2) for v in f.point],
        "lower_80": [round(v, 2) for v in f.quantiles.get("0.1", [])],
        "upper_80": [round(v, 2) for v in f.quantiles.get("0.9", [])],
        "lower_95": [round(v, 2) for v in f.quantiles.get("0.025", [])],
        "upper_95": [round(v, 2) for v in f.quantiles.get("0.975", [])],
        "horizon_total_demand": round(sum(f.point), 1),
        "diagnostics": {
            "characterization": f.diagnostics.characterization,
            "n_obs": f.diagnostics.n_obs,
            "mape_backtest_pct": (round(f.diagnostics.mape_backtest, 1)
                                  if f.diagnostics.mape_backtest is not None else None),
            "crps_backtest": (round(f.diagnostics.crps_backtest, 3)
                              if f.diagnostics.crps_backtest is not None else None),
            "n_backtest_folds": f.diagnostics.n_backtest_folds,
        },
        "caveats": f.caveats,
    }


# ---------- compute_reorder ----------

def _compute_reorder(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    sku_id = str(args.get("sku_id", "")).strip().upper()
    if not sku_id:
        raise ToolExecutionError("sku_id is required")
    overrides = RecommendationOverrides(
        service_level=args.get("service_level"),
        lead_time_days_override=args.get("lead_time_days_override"),
        horizon_periods=args.get("horizon_periods"),
    )
    try:
        rec = recommend_sku(dataset_id, sku_id, overrides=overrides)
    except ValueError as e:
        raise ToolExecutionError(str(e)) from e
    return {
        "sku_id": rec.sku_id,
        "policy_name": rec.policy_name,
        "abc_xyz": f"{rec.abc_class}{rec.xyz_class}",
        "recommended_order_qty": round(rec.recommended_order_qty, 1),
        "reorder_point": round(rec.reorder_point, 1) if rec.reorder_point is not None else None,
        "safety_stock": round(rec.safety_stock, 1),
        "expected_stockout_prob": round(rec.expected_stockout_prob, 4),
        "expected_fill_rate": round(rec.expected_fill_rate, 4),
        "expected_holding_cost_annual": round(rec.expected_holding_cost_annual, 2),
        "expected_total_cost_annual": round(rec.expected_total_cost_annual, 2),
        "parameters": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in rec.parameters.items()},
        "caveats": rec.caveats,
    }


# ---------- run_scenario ----------

def _run_scenario(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    sku_ids = [str(s).strip().upper() for s in (args.get("sku_ids") or []) if s]
    if not sku_ids:
        raise ToolExecutionError("at least one sku_id is required")
    perturbations = args.get("perturbations") or {}

    base_overrides = RecommendationOverrides()
    scenario_overrides = RecommendationOverrides(
        service_level=perturbations.get("service_level_target"),
        holding_cost_rate=perturbations.get("holding_cost_rate"),
    )
    if "lead_time_multiplier" in perturbations:
        # Need to apply per-SKU using each SKU's current LT
        pass  # handled inline below

    out = []
    for sid in sku_ids:
        try:
            base = recommend_sku(dataset_id, sid, overrides=base_overrides)
        except ValueError as e:
            out.append({"sku_id": sid, "error": str(e)})
            continue

        sku_overrides = RecommendationOverrides(
            service_level=scenario_overrides.service_level,
            holding_cost_rate=scenario_overrides.holding_cost_rate,
        )
        if "lead_time_multiplier" in perturbations:
            # Pull current LT from SKU history, multiply
            with open_dataset(dataset_id, read_only=True) as conn:
                lt_mean = conn.execute(
                    "SELECT AVG(lead_time_days) FROM panel WHERE sku_id = ? AND lead_time_days IS NOT NULL",
                    [sid],
                ).fetchone()[0]
            if lt_mean is not None:
                sku_overrides.lead_time_days_override = float(lt_mean) * float(perturbations["lead_time_multiplier"])
        try:
            scen = recommend_sku(dataset_id, sid, overrides=sku_overrides)
        except ValueError as e:
            out.append({"sku_id": sid, "error": str(e)})
            continue
        out.append({
            "sku_id": sid,
            "base": {
                "policy": base.policy_name,
                "order_qty": round(base.recommended_order_qty, 1),
                "reorder_point": round(base.reorder_point, 1) if base.reorder_point else None,
                "safety_stock": round(base.safety_stock, 1),
                "stockout_prob": round(base.expected_stockout_prob, 4),
                "annual_cost": round(base.expected_total_cost_annual, 2),
            },
            "scenario": {
                "policy": scen.policy_name,
                "order_qty": round(scen.recommended_order_qty, 1),
                "reorder_point": round(scen.reorder_point, 1) if scen.reorder_point else None,
                "safety_stock": round(scen.safety_stock, 1),
                "stockout_prob": round(scen.expected_stockout_prob, 4),
                "annual_cost": round(scen.expected_total_cost_annual, 2),
            },
            "delta": {
                "safety_stock": round(scen.safety_stock - base.safety_stock, 1),
                "annual_cost": round(scen.expected_total_cost_annual - base.expected_total_cost_annual, 2),
            },
        })
    return {"perturbations_applied": perturbations, "results": out}


# ---------- get_aggregate_stats ----------

def _get_aggregate_stats(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel").fetchdf()
    if panel.empty:
        return {"n_skus": 0}
    frequency = infer_frequency(panel["date"]) or "W"
    annualization = {"D": 365, "W": 52, "M": 12}[frequency]
    assignments = classify_abc_xyz(panel, annualization_factor=annualization)
    abc_counts = {"A": 0, "B": 0, "C": 0}
    xyz_counts = {"X": 0, "Y": 0, "Z": 0}
    for a in assignments:
        abc_counts[a.abc] += 1
        xyz_counts[a.xyz] += 1

    inventory_value = None
    if "on_hand" in panel.columns and panel["on_hand"].notna().any() and "unit_cost" in panel.columns:
        last = panel.sort_values("date").groupby("sku_id").tail(1)
        inventory_value = float((last["on_hand"].fillna(0) * last["unit_cost"].fillna(0)).sum())

    return {
        "n_skus": int(panel["sku_id"].nunique()),
        "frequency": frequency,
        "date_range": [str(panel["date"].min().date()), str(panel["date"].max().date())],
        "total_revenue_annual": round(sum(a.revenue_annual for a in assignments), 2),
        "total_inventory_value": round(inventory_value, 2) if inventory_value is not None else None,
        "abc_counts": abc_counts,
        "xyz_counts": xyz_counts,
        "abc_xyz_heatmap": heatmap_counts(assignments),
        "n_skus_low_history": sum(1 for sku in panel.groupby("sku_id").size() if sku < 13),
    }


# ---------- Day 10 tools ----------

def _get_data_quality_report(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    from apps.api.config import get_settings
    settings = get_settings()
    report_path = settings.data_path / "reports" / f"{dataset_id}.json"
    if not report_path.exists():
        raise ToolExecutionError("no DQ report for this dataset (it should have been written on /confirm)")
    from apps.api.assertions.schemas import DataQualityReport
    report = DataQualityReport.model_validate_json(report_path.read_text())
    return {
        "composite_score": report.composite_score,
        "components": [{"name": c.name, "score": c.score, "weight": c.weight, "notes": c.notes}
                       for c in report.components],
        "assertions": [{
            "code": a.code, "severity": a.severity.value, "field": a.field,
            "message": a.message, "offending_row_count": a.offending_row_count,
            "skus_affected": a.skus_affected,
        } for a in report.assertions],
        "n_rows": report.n_rows,
        "n_skus": report.n_skus,
        "skus_low_history": report.skus_low_history[:20],
        "skus_with_business_logic_issues": report.skus_with_business_logic_issues[:20],
    }


def _compare_to_m5(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    from apps.api.assertions.statistical import _matched_dept_row, metrics_for_sku
    from apps.api.m5.loader import dq_reference_dists

    sku_id = str(args.get("sku_id", "")).strip().upper()
    if not sku_id:
        raise ToolExecutionError("sku_id is required")

    with open_dataset(dataset_id, read_only=True) as conn:
        df = conn.execute(
            "SELECT date, demand, category FROM panel WHERE sku_id = ? ORDER BY date",
            [sku_id],
        ).fetchdf()
    if df.empty:
        raise ToolExecutionError(f"sku '{sku_id}' not in dataset")

    arr = df["demand"].to_numpy(dtype=float)
    category = df["category"].iloc[0] if "category" in df.columns and pd.notna(df["category"].iloc[0]) else None
    metrics = metrics_for_sku(arr)

    ref = dq_reference_dists()
    if ref is None:
        return {"sku_id": sku_id, "metrics": metrics, "comparisons": [],
                "note": "M5 reference distributions not available."}

    comparisons = []
    for metric_name, value in metrics.items():
        ref_row = _matched_dept_row(ref, category, metric_name)
        if ref_row is None:
            continue
        if value <= ref_row["p1"]:
            position = "below_p1"
        elif value <= ref_row["p25"]:
            position = "p1_to_p25"
        elif value <= ref_row["p75"]:
            position = "p25_to_p75"
        elif value <= ref_row["p99"]:
            position = "p75_to_p99"
        else:
            position = "above_p99"
        comparisons.append({
            "metric": metric_name,
            "user_value": round(float(value), 4),
            "m5_p1": round(float(ref_row["p1"]), 4),
            "m5_p50": round(float(ref_row["p50"]), 4),
            "m5_p99": round(float(ref_row["p99"]), 4),
            "position": position,
            "matched_dept": str(ref_row["dept_id"]),
        })

    return {"sku_id": sku_id, "category": category, "comparisons": comparisons}


def _analyze_dataframe(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    from apps.api.llm.sandbox import SandboxQueryError, execute_query
    query = args.get("query") or {}
    if not isinstance(query, dict):
        raise ToolExecutionError("query must be an object")
    fmt = str(args.get("format") or "table").lower()
    if fmt not in {"table", "chart_data"}:
        raise ToolExecutionError("format must be 'table' or 'chart_data'")
    with open_dataset(dataset_id, read_only=True) as conn:
        panel = conn.execute("SELECT * FROM panel").fetchdf()
    try:
        result = execute_query(panel, query)
    except SandboxQueryError as e:
        raise ToolExecutionError(str(e)) from e
    if fmt == "chart_data":
        result["chart_hint"] = _infer_chart_hint(query, result)
    return result


def _infer_chart_hint(query: dict, result: dict) -> dict:
    """Pick a default Vega-Lite mark + x/y encoding from the query shape.

    Heuristic: date in groupby → line over time; categorical groupby → bar; otherwise no hint.
    The agent should pass the result directly into make_chart's spec.data.values and copy mark/x/y.
    """
    rows = result.get("rows") or []
    if not rows:
        return {"mark": "bar", "x": None, "y": None, "note": "empty result; no chart"}
    columns = list(rows[0].keys())
    groupby = query.get("groupby") or []
    aggregate = query.get("aggregate") or {}
    agg_cols = list(aggregate.keys())

    x_col: str | None = None
    y_col: str | None = None
    mark: str = "bar"

    if groupby and "date" in groupby:
        mark = "line"
        x_col = "date"
        y_col = agg_cols[0] if agg_cols else (columns[1] if len(columns) > 1 else None)
    elif groupby:
        mark = "bar"
        x_col = groupby[0]
        y_col = agg_cols[0] if agg_cols else (columns[1] if len(columns) > 1 else None)
    else:
        mark = "bar"
        x_col = columns[0] if columns else None
        y_col = columns[1] if len(columns) > 1 else None

    x_type = "temporal" if x_col == "date" else "nominal"
    y_type = "quantitative"
    return {
        "mark": mark,
        "x": {"field": x_col, "type": x_type} if x_col else None,
        "y": {"field": y_col, "type": y_type} if y_col else None,
        "note": (
            "Pass `rows` as `spec.data.values` in make_chart; use this mark/x/y in `spec.encoding`. "
            "Override the hint when the user asked for a specific chart type."
        ),
    }


def _make_chart(dataset_id: str, args: dict) -> Any:
    """Pass-through validator. The frontend renders Vega-Lite specs from the tool result."""
    spec = args.get("spec")
    if not isinstance(spec, dict):
        raise ToolExecutionError("spec must be a Vega-Lite object")
    title = args.get("title")
    return {"title": title, "spec": spec, "_render": "vega-lite"}


def _submit_plan(dataset_id: str, args: dict) -> Any:
    """Pass-through. The auto-plan endpoint extracts this tool call from the response
    and validates the contents against the panel + suppliers tables.
    """
    if not isinstance(args, dict):
        raise ToolExecutionError("submit_plan input must be an object")
    if "draft_pos" not in args:
        raise ToolExecutionError("submit_plan requires draft_pos")
    return args


def _nl_to_query(dataset_id: str, args: dict) -> Any:
    _require_dataset(dataset_id)
    from apps.api.llm.nl_query import run_nl_query

    question = str(args.get("question") or "").strip()
    if not question:
        raise ToolExecutionError("question is required")
    if len(question) > 500:
        raise ToolExecutionError("question is too long")
    return run_nl_query(dataset_id, question)


def _plan_reorder_week(dataset_id: str, args: dict) -> Any:
    from apps.api.inventory.recommend import plan_reorder_week

    service_level = float(args.get("service_level", 0.95))
    if not 0.5 <= service_level <= 0.999:
        raise ToolExecutionError(f"service_level must be in [0.5, 0.999]; got {service_level}")
    budget_cap = args.get("budget_cap_usd")
    if budget_cap is not None:
        budget_cap = float(budget_cap)
        if budget_cap < 0:
            raise ToolExecutionError("budget_cap_usd must be >= 0")
    top_n = int(args.get("top_n", 25))
    if not 1 <= top_n <= 100:
        raise ToolExecutionError(f"top_n must be in [1, 100]; got {top_n}")
    return plan_reorder_week(
        dataset_id,
        service_level=service_level,
        budget_cap_usd=budget_cap,
        top_n=top_n,
    )


import threading

# Per-thread dispatcher. FastAPI runs sync handlers in a thread pool, so two concurrent
# /chat requests would otherwise race on a single module-global dispatcher — which would
# cause request A's Planner to invoke request B's specialist against B's dataset_id
# (closed over in the orchestrator's `_dispatcher` lambda). That's cross-tenant data
# bleed under concurrent load. threading.local() isolates the dispatcher per thread.
_dispatcher_local = threading.local()


def _set_active_dispatcher(fn) -> None:
    _dispatcher_local.fn = fn


def _clear_active_dispatcher() -> None:
    _dispatcher_local.fn = None


def _get_active_dispatcher():
    return getattr(_dispatcher_local, "fn", None)


def _dispatch_specialist(dataset_id: str, args: dict) -> Any:
    """Bridge from the Planner's tool call into the orchestrator's specialist dispatcher.

    The orchestrator calls `_set_active_dispatcher(...)` before running the Planner; we
    look it up here (per-thread) and return the SpecialistResult as a dict so the Planner
    sees structured findings on the next iteration.
    """
    dispatcher = _get_active_dispatcher()
    if dispatcher is None:
        raise ToolExecutionError(
            "dispatch_specialist can only be called inside the Planner (no active dispatcher)."
        )
    specialist = str(args.get("specialist", "")).strip()
    if specialist not in {"forecaster", "risk", "buyer"}:
        raise ToolExecutionError(f"unknown specialist: {specialist!r}")
    sub_question = str(args.get("sub_question") or "").strip()
    if not sub_question:
        raise ToolExecutionError("sub_question is required and cannot be empty")
    context = args.get("context")
    if context is not None and not isinstance(context, str):
        raise ToolExecutionError("context must be a string")

    result = dispatcher(specialist, sub_question, context)
    return {
        "specialist": result.specialist,
        "summary": result.summary,
        "key_findings": result.key_findings,
        "n_tool_calls": len(result.tool_calls),
        "tool_call_names": [tc.name for tc in result.tool_calls],
        "stop_reason": result.stop_reason,
        "iterations": result.iterations,
        "usage_usd": round(result.usage.estimated_usd, 4),
    }


def _submit_final_answer(dataset_id: str, args: dict) -> Any:
    """Pass-through. The orchestrator extracts this tool call to surface the final text."""
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ToolExecutionError("submit_final_answer requires non-empty text")
    return {"text": text.strip()}


_ALLOWED_ANOMALY_CAUSES = {
    "promotion_or_discount",
    "holiday_or_calendar",
    "weather_event",
    "supplier_stockout",
    "data_entry_error",
    "regime_shift",
    "competitive_event",
    "category_wide_trend",
    "unclear",
}
_ALLOWED_ANOMALY_ADJUSTMENTS = {"ignore", "investigate_manually", "override_forecast", "flag_for_review"}


def _submit_anomaly_explanation(dataset_id: str, args: dict) -> Any:
    """Pass-through validator. anomaly_explainer.py extracts the tool call from the response
    rather than reading this return value, but we still validate so a malformed submission
    fails loudly inside the loop."""
    if not isinstance(args, dict):
        raise ToolExecutionError("submit_anomaly_explanation requires object args")
    cause = str(args.get("cause", "")).strip()
    if cause not in _ALLOWED_ANOMALY_CAUSES:
        raise ToolExecutionError(f"cause must be one of {sorted(_ALLOWED_ANOMALY_CAUSES)}; got {cause!r}")
    adj = str(args.get("suggested_adjustment", "")).strip()
    if adj not in _ALLOWED_ANOMALY_ADJUSTMENTS:
        raise ToolExecutionError(f"suggested_adjustment must be one of {sorted(_ALLOWED_ANOMALY_ADJUSTMENTS)}; got {adj!r}")
    try:
        conf = float(args.get("confidence", 0.0))
    except (TypeError, ValueError):
        raise ToolExecutionError("confidence must be a float in [0, 1]")
    if not 0.0 <= conf <= 1.0:
        raise ToolExecutionError(f"confidence must be in [0, 1]; got {conf}")
    evidence = args.get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(e, str) and e.strip() for e in evidence):
        raise ToolExecutionError("evidence must be a non-empty list of non-empty strings")
    if len(evidence) > 5:
        raise ToolExecutionError("evidence may have at most 5 items")
    return {
        "cause": cause,
        "confidence": conf,
        "evidence": [e.strip() for e in evidence],
        "suggested_adjustment": adj,
    }


EXECUTORS = {
    "query_skus": _query_skus,
    "get_sku_details": _get_sku_details,
    "get_forecast": _get_forecast,
    "compute_reorder": _compute_reorder,
    "run_scenario": _run_scenario,
    "get_aggregate_stats": _get_aggregate_stats,
    "get_data_quality_report": _get_data_quality_report,
    "compare_to_m5": _compare_to_m5,
    "analyze_dataframe": _analyze_dataframe,
    "make_chart": _make_chart,
    "submit_plan": _submit_plan,
    "plan_reorder_week": _plan_reorder_week,
    "nl_to_query": _nl_to_query,
    "dispatch_specialist": _dispatch_specialist,
    "submit_final_answer": _submit_final_answer,
    "submit_anomaly_explanation": _submit_anomaly_explanation,
}


def execute_tool(name: str, dataset_id: str, arguments: dict) -> Any:
    fn = EXECUTORS.get(name)
    if fn is None:
        raise ToolExecutionError(f"unknown tool: {name}")
    return fn(dataset_id, arguments or {})
