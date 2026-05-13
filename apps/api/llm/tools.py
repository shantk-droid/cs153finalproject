"""JSON-schema tool definitions exposed to Claude.

Six v1 tools per the plan:
- query_skus(filters, limit)
- get_sku_details(sku_id)
- get_forecast(sku_id, horizon_periods)
- compute_reorder(sku_id, service_level, lead_time_days_override)
- run_scenario(sku_ids, perturbations)
- get_aggregate_stats(group_by)

Days 9–10 will add: get_data_quality_report, compare_to_m5, analyze_dataframe, make_chart.
"""

from __future__ import annotations

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "query_skus",
        "description": (
            "List SKUs in the loaded dataset, with filters. Use this when the user asks 'which SKUs', "
            "'show me SKUs in category X', or wants to narrow down before fetching details. Returns "
            "up to `limit` SKUs sorted by annualized revenue (descending by default)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Exact match on the category column."},
                "supplier": {"type": "string", "description": "Exact match on the supplier column."},
                "abc": {"type": "string", "enum": ["A", "B", "C"], "description": "Filter by ABC class."},
                "xyz": {"type": "string", "enum": ["X", "Y", "Z"], "description": "Filter by XYZ class."},
                "sort_by": {
                    "type": "string",
                    "enum": ["sku_id", "revenue_annual", "cv_demand", "last_demand"],
                    "default": "revenue_annual",
                },
                "sort_dir": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_sku_details",
        "description": (
            "Get the full record for one SKU: last demand, on-hand, supplier, category, "
            "ABC/XYZ class, observation count, and the diagnostics needed to caveat any forecast."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {"type": "string", "description": "Exact SKU ID (case-insensitive)."},
            },
            "required": ["sku_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_forecast",
        "description": (
            "Run a demand forecast for a SKU and return the point forecast, 80%/95% prediction "
            "intervals, and backtest accuracy diagnostics (MAPE, CRPS). Use for any 'how much will "
            "we sell', 'demand forecast', or 'expected demand' question. Refuses with a clear error "
            "if the SKU has fewer than 8 observations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {"type": "string"},
                "horizon_periods": {"type": "integer", "minimum": 1, "maximum": 52, "default": 12},
            },
            "required": ["sku_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "compute_reorder",
        "description": (
            "Compute the inventory recommendation (policy + order qty + reorder point + safety stock + "
            "stockout risk + expected annual cost) for a SKU. Use when the user asks 'how much should "
            "I order', 'what's my reorder point', 'safety stock'. Service level defaults to 0.95; "
            "override only if the user explicitly asks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {"type": "string"},
                "service_level": {"type": "number", "minimum": 0.5, "maximum": 0.999, "default": 0.95},
                "lead_time_days_override": {
                    "type": "number",
                    "description": "Optional override for lead time in days. Only set when the user provides one.",
                },
                "horizon_periods": {"type": "integer", "minimum": 1, "maximum": 52, "default": 12},
            },
            "required": ["sku_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_scenario",
        "description": (
            "Re-run the recommendation under perturbed inputs to answer 'what if' questions. Common "
            "perturbations: lead-time multiplier (e.g. 2.0 = double), demand growth (e.g. 0.2 = +20% YoY), "
            "service-level target. Returns base-case + scenario side by side. Limit `sku_ids` to the "
            "specific SKUs the user named, or top revenue SKUs (5–10) if none named."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                "perturbations": {
                    "type": "object",
                    "properties": {
                        "lead_time_multiplier": {"type": "number"},
                        "demand_growth": {"type": "number", "description": "Annual fractional growth (0.2 = +20%)."},
                        "service_level_target": {"type": "number", "minimum": 0.5, "maximum": 0.999},
                        "holding_cost_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["sku_ids", "perturbations"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_aggregate_stats",
        "description": (
            "Portfolio-level metrics: total SKUs, annual revenue, inventory value, average days of "
            "cover, ABC/XYZ counts and 9-cell heatmap, count of low-history SKUs flagged for cold-start. "
            "Use for any 'how many SKUs', 'total revenue', 'how much inventory', portfolio question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_data_quality_report",
        "description": (
            "Return the upload's data-quality report: composite score 0–100, the five sub-scores "
            "(completeness, plausibility, statistical fit vs M5, history depth, stationarity), "
            "and the assertions that triggered. Use when the user asks 'how clean is my data', "
            "'what's wrong with my data', 'data quality', 'are there issues'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "compare_to_m5",
        "description": (
            "Compare a SKU's series-level statistics (CV-of-demand, intermittency rate, seasonality "
            "strength, trend slope, regime-shift score) to the M5 Walmart reference distribution for "
            "the matched category. Use when the user asks 'is my SKU normal', 'how does X compare to "
            "real retail', 'is my data weird'. Returns each metric value + the M5 percentile band."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {"type": "string"},
            },
            "required": ["sku_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "analyze_dataframe",
        "description": (
            "Run an ad-hoc analytical query against the SKU panel using a restricted JSON DSL. "
            "Use this for any 'top N', 'how many ... where', 'sum of ... by category' type question "
            "that the other tools don't directly answer. Always prefer get_aggregate_stats / query_skus "
            "when they fit; reach for analyze_dataframe only for novel slices. The query language: "
            "{filter: [{col,op,value}], groupby: [col], aggregate: {col: agg}, sort_by, sort_dir, limit}. "
            "Allowed columns: sku_id, date, demand, on_hand, lead_time_days, unit_cost, unit_price, "
            "supplier, category. Allowed ops: ==, !=, <, <=, >, >=, in, not in, contains, is_null, "
            "not_null. Allowed aggs: sum, mean, median, min, max, count, nunique, std, first, last."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "col": {"type": "string"},
                                    "op": {"type": "string"},
                                    "value": {},
                                },
                                "required": ["col", "op"],
                            },
                        },
                        "groupby": {"type": "array", "items": {"type": "string"}},
                        "aggregate": {"type": "object", "additionalProperties": {"type": "string"}},
                        "sort_by": {"type": "string"},
                        "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "additionalProperties": False,
                },
                "format": {
                    "type": "string",
                    "enum": ["table", "chart_data"],
                    "default": "table",
                    "description": (
                        "Set 'chart_data' when the result will be fed into make_chart. The response "
                        "then includes a `chart_hint` with suggested mark/x/y, ready to copy into "
                        "the Vega-Lite spec.encoding."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_plan",
        "description": (
            "Submit the final weekly purchase-order plan. Call this exactly once at the end "
            "of the auto-plan agent workflow. Each draft PO bundles SKUs from one supplier; "
            "include a one-sentence rationale referencing the highest-revenue line and the "
            "stockout risk. Set expedite=true when stockout_prob > 0.5 or expedite_flag is set."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "1-2 sentence overall summary."},
                "draft_pos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "supplier_name": {"type": "string"},
                            "supplier_id": {"type": "string"},
                            "lines": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "sku_id": {"type": "string"},
                                        "qty": {"type": "number"},
                                        "rationale": {"type": "string"},
                                    },
                                    "required": ["sku_id", "qty"],
                                },
                                "minItems": 1,
                            },
                            "expedite": {"type": "boolean"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["supplier_name", "lines", "rationale"],
                    },
                },
            },
            "required": ["summary", "draft_pos"],
        },
    },
    {
        "name": "plan_reorder_week",
        "description": (
            "Generate a one-week reorder plan covering the most urgent SKUs in the dataset. "
            "Use when the user asks 'plan my reorders for the week', 'what should I order this week', "
            "'give me a reorder plan with a budget of $X', or any planning-level question that spans "
            "multiple SKUs at once. Items are ranked by stockout-prob × revenue-at-risk; with a "
            "`budget_cap_usd`, the plan greedily picks by risk-per-dollar so the cap is respected, "
            "and items that don't fit are returned in `deferred_items` with a reason. Each line "
            "includes a one-line rationale ready to surface to a buyer. Prefer this over calling "
            "compute_reorder for every SKU individually."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service_level": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 0.999,
                    "default": 0.95,
                    "description": (
                        "Informational — pass through the service-level commitment the user mentioned. "
                        "Affects how the plan is framed, not the underlying queue qty (queue uses a "
                        "95% internal default)."
                    ),
                },
                "budget_cap_usd": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Optional USD budget cap. When set, the plan greedily picks items by "
                        "risk-per-dollar until the cap is hit. Items that don't fit go to "
                        "`deferred_items` with reason='budget_exceeded'."
                    ),
                },
                "top_n": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 25,
                    "description": "Maximum number of SKUs to include in the plan.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "nl_to_query",
        "description": (
            "Translate a natural-language question into a read-only DuckDB SELECT against the "
            "panel/suppliers/skus tables. Use for arbitrary ad-hoc slices that don't fit the "
            "structured analyze_dataframe DSL (complex GROUP BY combinations, multi-column filters, "
            "ORDER BY tricks). The returned SQL is validated against an allowlist (only SELECT, "
            "only allowed tables/columns, no JOINs across systems, no filesystem functions) and "
            "executed in read-only mode. Returns rows + columns plus the SQL itself for "
            "transparency. If the question can't be answered safely, returns an error message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The user's question in natural language.",
                    "minLength": 4,
                    "maxLength": 500,
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
    {
        "name": "make_chart",
        "description": (
            "Return a Vega-Lite chart spec for the frontend to render inline. Use sparingly: when "
            "the user asks for a visualization, comparison, distribution, or 'show me'. Provide a "
            "complete, valid Vega-Lite v5 spec with `data.values` populated from prior tool results. "
            "Don't reference external URLs. Keep it small (<= 200 rows) — the frontend re-renders on every event."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "spec": {
                    "type": "object",
                    "description": "A complete Vega-Lite v5 spec including $schema, data, and mark/encoding.",
                },
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
    },
]


# Planner-only tools — not registered in TOOL_DEFINITIONS so they don't show up in
# single-agent tool listings. They're appended to the Planner's `tool_subset` and routed
# through the same EXECUTORS dict.

ANOMALY_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "submit_anomaly_explanation",
        "description": (
            "Final structured submission for an anomaly investigation. Call EXACTLY once at "
            "the end of the explainer flow. Captures the LLM's structured judgement so the UI "
            "can render distinct cells (cause, confidence, evidence, suggested_adjustment) "
            "alongside the prose narrative."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cause": {
                    "type": "string",
                    "enum": [
                        "promotion_or_discount",
                        "holiday_or_calendar",
                        "weather_event",
                        "supplier_stockout",
                        "data_entry_error",
                        "regime_shift",
                        "competitive_event",
                        "category_wide_trend",
                        "unclear",
                    ],
                    "description": "Most likely cause. Pick `unclear` if telemetry alone cannot support a guess.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Subjective confidence in the cause [0,1]. Penalize when evidence is thin.",
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "1-5 bullet points naming specific evidence from tool calls: SKU IDs, "
                        "M5 percentile bands, calendar markers, sibling SKU patterns. Do NOT "
                        "invent — every bullet must trace to a tool result."
                    ),
                },
                "suggested_adjustment": {
                    "type": "string",
                    "enum": ["ignore", "investigate_manually", "override_forecast", "flag_for_review"],
                    "description": (
                        "Action recommendation. `ignore` when the event is explained by a known "
                        "non-recurring driver. `override_forecast` only when there's strong "
                        "evidence the model is structurally wrong. `investigate_manually` is the "
                        "safe default when confidence is below ~0.4."
                    ),
                },
            },
            "required": ["cause", "confidence", "evidence", "suggested_adjustment"],
            "additionalProperties": False,
        },
    },
]


PLANNER_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "dispatch_specialist",
        "description": (
            "Hand a focused sub-question to one specialist (forecaster, risk, or buyer). "
            "The specialist runs its own scoped tool-use loop and returns a structured summary "
            "with key findings. Each dispatch is one of your 3-call budget — choose the best "
            "specialist and write a tight, single-purpose sub-question. Pass `context` (≤200 chars) "
            "when prior specialists' findings should inform this one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "specialist": {
                    "type": "string",
                    "enum": ["forecaster", "risk", "buyer"],
                },
                "sub_question": {
                    "type": "string",
                    "description": "The focused question to hand off. Be specific — name SKUs if known.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional one-sentence summary of prior findings to thread in.",
                },
            },
            "required": ["specialist", "sub_question"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_final_answer",
        "description": (
            "Emit the final synthesized answer to the user. Call exactly once when you have "
            "enough from specialists. Lead with the recommendation; cite specific SKU IDs, "
            "supplier names, and numbers. 4-8 sentences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
]

# Public registry: chat tools + planner tools + anomaly explainer tool. Single-agent uses the
# first list; the Planner uses planner tools via tool_subset; the anomaly explainer agent uses
# the anomaly tool via tool_subset. _filter_tools in loop.py searches ALL_TOOL_DEFINITIONS so
# any of these names can be requested by a sub-agent.
ALL_TOOL_DEFINITIONS: list[dict] = TOOL_DEFINITIONS + PLANNER_TOOL_DEFINITIONS + ANOMALY_TOOL_DEFINITIONS


def tool_names() -> list[str]:
    return [t["name"] for t in TOOL_DEFINITIONS]


def all_tool_names() -> list[str]:
    return [t["name"] for t in ALL_TOOL_DEFINITIONS]
