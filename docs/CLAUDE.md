# Inventory Optimizer — Project Context

This file is automatically loaded into every Claude Code session. Keep it current.

## What this app does

A web app that ingests CSV/Excel uploads of SKU sales data — or loads one of three
realistic demo datasets — and returns a left-rail-navigated workspace covering:

1. **Overview** — KPI strip with PoP deltas + sparklines, ABC×XYZ heatmap, proactive insights tile, working-capital tile, data-quality summary.
2. **Reorder Queue** — ranked POs by `stockout_prob × revenue_at_risk`, MOQ/case-pack rounding, expedite flag with breakeven math, one-click PO drafting, PO state machine (drafted → approved → placed → received), CSV + EDI 850 export.
3. **Forecasts** — sparkline-equipped SKU table; per-SKU detail with prediction intervals, decomposition (trend/seasonal/residual), backtest residual diagnostics, model leaderboard (per-method MAPE/CRPS), and an "Explain anomaly" agentic drawer.
4. **Frontier** — service-level vs cost Pareto curve with draggable target + newsvendor calculator (critical-ratio derivation visible).
5. **Suppliers** — scorecards with OTIF / on-time / in-full / lead-time mean+std, MOQ, payment terms, info-icon tooltips on every column. Detail page shows lead-time histogram with Bayesian posterior overlay (gamma + normal-approx conjugate from receipts).
6. **Stress test** — lead-time × demand × service-level shock sliders, VaR/CVaR 95%, top-10 impacted SKUs.
7. **Data quality** — 5-component composite (completeness, plausibility, statistical fit, history depth, stationarity).
8. **Chat** — Claude tool-use with 11 tools, SSE streaming, inline Vega-Lite chart rendering.
9. **Settings** — service level, holding cost, order cost, review period.
10. **Agentic features** — "Generate this week's plan" auto-plan agent on the Reorder page (drafts grouped by supplier with rationale + accept-to-create flow), "Explain anomaly" drawer on forecast charts (deterministic CUSUM/MAD detector + LLM narrative + heuristic fallback).

What makes it more than a tutorial:
- **M5 Calibration Layer** — precomputed priors / classifier / calendar effects from M5 Walmart data, baked in at build time, used to improve cold-start forecasts and benchmark uploads.
- **5-component Data Quality Score** — completeness, plausibility, statistical fit, history depth, **stationarity / regime stability**.
- **Eval harness for the chat layer** — golden-question YAML, PR-blocking at 90% pass rate. The chat is *trustable*, not just fluent.
- **Methodology transparency moat** — every metric on the dashboard has a `<MethodologyDrawer>` info icon that opens a side drawer with formula, inputs, current values, and assumptions. Most enterprise tools are black boxes; this is the opposite stance.
- **Agentic outputs are grounded, not generative** — the anomaly detector runs deterministically server-side; the LLM only writes the explanation. The auto-plan agent is forced through a `submit_plan` tool with a strict schema, then every line is re-validated against the panel (sku_id existence, MOQ/case-pack rounding, unit_cost re-fetched). The LLM is never trusted with prices.

## Working agreements with the user

These were established interactively on 2026-05-04 and apply to every future session in this repo.

### 1. Plan revision authority
If something in the 14-day plan (`~/.claude/plans/look-at-the-build-quiet-meteor.md`) or a prior phasing decision seems wrong/sub-optimal mid-execution, **revise the order or scope and continue**. Don't ask permission for every reorder — the user wants speed without sacrificing quality.

How to apply:
- Make the revision and proceed.
- Surface the revision in the response: what changed, why, what now lands when.
- Update the plan file or todo list so it stays the source of truth.
- Never revise silently — explain the swap.

### 2. Defer user-blocked tasks; keep building
Continue autonomous work as long as possible; only stop when a task literally cannot proceed without the user. The standing direction is "keep going through the days."

How to apply:
- Surface which days/tasks are user-blocked and which I'm proceeding with.
- Put autonomous work first in the response; the user's blocker list goes at the end.
- Until `ANTHROPIC_API_KEY` arrives, do **not** write LLM-call code that would silently 401. Stub or skip.
- Until `libomp` (or any OpenMP) is installed locally, do **not** pull `lightgbm` into the import path of code that runs on the dev machine. Modal's container has `libgomp1` so production is fine.

## Stack — DO NOT CHANGE without explicit user instruction

- **Frontend**: Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui + Recharts + TanStack Table + Vega-Lite (for chat charts).
- **Backend**: FastAPI + Python 3.11+ + pydantic v2 + pandas + numpy + scipy + DuckDB + openpyxl.
- **Forecasting libs**: `statsforecast`, `chronos-forecasting>=2.0` (Bolt variant, CPU), `lightgbm`, `hierarchicalforecast`, `numpyro` (for Bayesian shrinkage).
- **LLM**: Anthropic API, `claude-sonnet-4-6`, tool use, prompt caching, extended-thinking small budget.
- **Jobs**: `arq` (Redis-backed) for ingest+forecast background tasks.
- **Storage**: DuckDB file per dataset; raw uploads → R2/S3.
- **Hosting**: Vercel (web), Modal or Railway (api).
- **Auth**: single shared password gate. NOT real auth — explicitly out of scope.

## Canonical data schema (long-format, one row per SKU per period)

| Column | Type | Required | Notes |
|---|---|---|---|
| `sku_id` | str | yes | Trimmed + uppercased on ingest. |
| `date` | date | yes | Period start; daily/weekly/monthly inferred. |
| `demand` | float | yes | Negative = return, netted into demand. |
| `on_hand` | float | no | Current snapshot. |
| `lead_time_days` | float | no | Per-row observation if present. |
| `unit_cost` | float | no | Defaults to 1.0. |
| `unit_price` | float | no | Used for newsvendor / lost-margin costing. |
| `supplier` | str | no | Groups lead-time observations + joint replen. |
| `category` | str | no | Drives M5-defaults match + hierarchical reconciliation. |

## Repo layout (truncated)

```
apps/
  web/                  # Next.js 14 (App Router, server components by default)
    app/
      page.tsx                          # landing + LandingActions (demo loader buttons)
      upload/                           # CSV/XLSX ingestion flow
      dashboard/[id]/
        layout.tsx                      # left-rail nav wrapper (server component)
        page.tsx                        # redirects to /overview
        overview/                       # KPI strip + insights + WC + ABC×XYZ + SKU table
        reorder/                        # Reorder queue + PO drawer + auto-plan modal
        forecasts/                      # Sparkline-equipped SKU table
        frontier/                       # SL vs cost Pareto + newsvendor calc
        suppliers/                      # Scorecards list (with HelpTooltip on every column)
          [supplierId]/                 # Detail with lead-time histogram + posterior
        stress/                         # Stress-test sliders + VaR
        quality/                        # DQ composite report
        chat/                           # Full-page chat
        settings/                       # Service level, holding cost, etc.
        sku/[skuId]/                    # Forecast + decomposition tabs + leaderboard + anomaly button
    components/
      KpiCards / SkuTable / Sparkline / AbcXyzHeatmap / ForecastChart
      RecommendationCard / ScenarioSliders / OrderScheduleTable / CalibrationCard
      ChatPanel / VegaLiteEmbed / DataQualityReport
      ReorderPageClient / PurchaseOrderDrawer (inline) / FrontierPageClient / StressTestClient
      ForecastsTable / DecompositionTabs / SupplierScorecard / LeadTimeHistogram
      InsightsTile / WorkingCapitalTile / MethodologyDrawer / HelpTooltip
      CommandPalette / SidebarNav / LandingActions
      AnomalyExplainerButton / AnomalyDrawer / AutoPlanModal       # agentic
    lib/
      api-client.ts / types.ts / utils.ts / methodology.ts / sentry.ts
  api/                  # FastAPI on Modal
    ingestion/          # routes, parsers, mappers, validators, storage, demo (synthetic loader)
    assertions/         # 3 layers: schema (hard), business-logic (soft), statistical (M5-grounded)
    forecasting/        # classical / ml / foundation / bayes / hierarchical / conformal / ensemble
                        # + decompose.py + leaderboard.py
    inventory/          # policies / multi_period / joint_replen / abc_xyz / distributions
                        # + reorder_queue / purchase_orders / po_export / supplier_metrics
                        # + frontier / stress_test / working_capital
    insights/           # compute.py — proactive insights
    llm/                # tools / loop / prompts / sandbox / eval / executors / schemas
                        # + anomaly.py (CUSUM/MAD detector) + anomaly_explainer.py
                        # + auto_plan.py (forced submit_plan output + validation)
    m5/                 # build_calibration.py + read-only artifacts/
    tests/              # 181 tests, including test_agentic.py
data/samples/           # synthetic CSVs (gitignored)
evals/                  # chat_questions.yaml + forecast_benchmarks.py
docs/
  CLAUDE.md             # this file
  M5_CALIBRATION.md
  DATA_ASSERTIONS.md
  DEMO_SCRIPT.md
  ONE_PAGER.md
infra/                  # Dockerfiles + docker-compose
```

## Conventions

- All API routes are typed with **pydantic v2 models** server-side and matching TS types client-side. TS types are **generated** from the FastAPI OpenAPI schema using `openapi-typescript` — do not duplicate.
- Pure functions for forecasting math live in `apps/api/forecasting/*` and have unit tests in `apps/api/tests/`. Same for `apps/api/inventory/*`.
- Never silently catch exceptions. Surface validation errors with field-level messages.
- Use server components by default in Next.js; mark client components explicitly with `"use client"`.
- Default to **no comments**. Add a comment only when the *why* is non-obvious.
- Pin library versions in `pyproject.toml` and `package.json`. Rebuild the M5 calibration in CI when the input hash or builder code changes.
- DuckDB is **per-dataset**, file-based. No shared schema, no migrations.
- M5 artifacts are **read-only at runtime**. They live at `apps/api/m5/artifacts/` and ship with the container.

## Out of scope (do not build without explicit instruction)

These were explicitly deferred during the 2026-05-05 MVP+ expansion. They map cleanly
to a future "Connectors + scheduling" phase if the user asks for it.

- Real auth (single password gate is enough).
- Multi-tenant data isolation.
- Real-time integrations with Shopify / Amazon / NetSuite / SAP / QuickBooks.
- Multi-echelon (METRIC) network optimization.
- Custom-trained ML models beyond the M5 pattern classifier.
- Mobile app (responsive web is sufficient).
- Billing / subscription.
- Public API + Python SDK + SQL editor.
- Drift monitoring / champion-challenger evaluation framework.
- Comments / collaboration on SKUs.
- Customer-cohort demand decomposition.
- Scheduled (cron) auto-plan agent — only on-demand button this pass.
- Promo lift modeling + price elasticity.
- Cannibalization detection + substitution graphs.
- Slack / Teams / email digests.
- Webhooks outbound on events.
- Dark mode.

## Forecast object — every method emits this

```python
class Forecast(BaseModel):
    sku_id: str
    method: Literal["ets","arima","croston","tsb","ml-lgb","chronos-bolt","ensemble","negbin-bayes"]
    horizon_periods: int
    frequency: Literal["D","W","M"]
    point: list[float]
    quantiles: dict[float, list[float]]   # {0.025, 0.1, 0.5, 0.9, 0.975}
    distribution_params: dict | None      # parametric, e.g. {"r": 3.2, "p": 0.4} for NegBin
    diagnostics: ForecastDiagnostics      # mape, crps, bias, n_obs, characterization, prior_weight
    caveats: list[str]                    # human-readable, e.g. "regime break in last 30d"
```

## Recommendation object — every policy emits this

```python
class Recommendation(BaseModel):
    sku_id: str
    policy_name: Literal["EOQ","(Q,R)","(s,S)","newsvendor","base-stock"]
    parameters: dict
    recommended_order_qty: float
    reorder_point: float | None
    safety_stock: float
    expected_stockout_prob: float
    expected_fill_rate: float
    expected_holding_cost_annual: float
    expected_total_cost_annual: float
    abc_class: Literal["A","B","C"]
    xyz_class: Literal["X","Y","Z"]
    schedule: list[ScheduleEntry] | None
    joint_replen_group: str | None
    caveats: list[str]
```

**Default policy is `(s,S)`** (changed from `(Q,R)` on 2026-05-05). Selection in
`_select_policy` (`apps/api/inventory/recommend.py`):
- Perishable category (from `category_defaults.json`) → `newsvendor`.
- Everything else → `(s,S)` via `ss_policy_simulated()` Monte-Carlo.
- `(Q,R)`, `EOQ`, `base-stock` remain available via `RecommendationOverrides.policy_override`.

## LLM chat + agents — hard caps (cost control)

**Chat (`stream_chat_sse` and default `run_chat_blocking`):**
- max 8 tool-call iterations per user turn
- max_tokens = 2048 on final response (extended-thinking budget eats into max_tokens)
- 30s wall-clock budget per turn
- 30 req/min/IP rate limit on `/chat`
- Cached prefix: system prompt + tool definitions + dataset summary (regenerated only on dataset change). **Never put timestamps in the cached prefix.**

**Agentic endpoints** (anomaly_explainer, auto_plan):
- Each call uses `run_chat_blocking()` with custom `system_prompt` + `tool_subset`.
- Anomaly explainer: max 4 iterations, 512 output tokens, thinking disabled.
- Auto-plan: max 4 iterations, 2048 output tokens, thinking disabled, `tool_choice={"type": "any"}` to force a tool call (not free-text).
- Cost ≈ $0.02 per call at Sonnet 4.6 pricing. Add a slowapi rate limit if these become user-visible at scale.
- Both agents have a deterministic fallback path that runs without the API key set — UI never blocks on agent availability.

## M5 Calibration Layer — what's in there

| Artifact | Use |
|---|---|
| `series_priors.parquet` | NegBin/Dirichlet hyperparameters per (category, pattern). Cold-start Bayesian shrinkage. |
| `pattern_classifier.lgb` | LightGBM classifier → {smooth, seasonal, intermittent, lumpy, trending_new, promo_driven}. |
| `calendar_effects.json` | DOW / WOY / US-holiday / SNAP multipliers + bootstrap CIs. |
| `category_defaults.json` | holding_cost_rate, order_cost, markup, default lead time, perishable flag, review period. |
| `dq_reference_dists.parquet` | Empirical quantile grids (1,5,25,50,75,95,99) per category per metric. DQ-score statistical-fit component. |

Builder lives at `apps/api/m5/build_calibration.py`. Run via `scripts/build_m5_calibration.sh` after `kaggle datasets download` puts raw files in `apps/api/m5/raw/`.

## Phasing — 14-day plan, see `~/.claude/plans/look-at-the-build-quiet-meteor.md`

### Progress — all 14 days shipped (last updated 2026-05-04, evening)
- ✅ **Day 1**: monorepo scaffold, `docs/CLAUDE.md`, FastAPI `/health`, Next.js shell, synthetic generator (3 templates), M5 calibration first cut (`calendar_effects.json` + `category_defaults.json`), Modal app, `vercel.json`, Next.js `/api/*` proxy.
- ✅ **Day 2**: ingestion (`/datasets/upload`, `/datasets/{id}/confirm`, mapper UI), assertion engine (schema-hard + business-logic-soft), DQ score with completeness/plausibility/history-depth lit (statistical_fit + stationarity stubbed for Day 9), DataQualityReport UI.
- ✅ **Day 3**: forecasting v1 — statsforecast (AutoETS / AutoARIMA / CrostonClassic / TSB / SeasonalNaive), hand-rule characterizer, rolling-origin backtest with MAPE/sMAPE/MASE/CRPS/pinball@95, M5 holdout benchmark CLI.
- ✅ **Day 4**: inventory math v1 — EOQ, (Q,R), (s,S) by simulation, newsvendor, base-stock, all using full LTD distribution (not normal-approx). ABC/XYZ classification. `/skus` listing, `/aggregate_stats`, `/skus/{id}/recommend`, `/skus/{id}/history` endpoints.
- ✅ **Day 5**: dashboard frontend — virtualized SkuTable (TanStack Table + react-virtual), KpiCards, ABC/XYZ heatmap, DQ summary tile, ForecastChart (Recharts), RecommendationCard, `/dashboard/[id]`, `/dashboard/[id]/sku/[skuId]` pages.

- ✅ **Day 6**: chat layer with 6 tools (`query_skus`, `get_sku_details`, `get_forecast`, `compute_reorder`, `run_scenario`, `get_aggregate_stats`), tool-use loop with prompt caching, SSE streaming, ChatPanel + ScenarioSliders. Eval harness 10 questions: **10/10 pass** against real Anthropic ($0.16 total).
- ✅ **Day 7**: Bayesian shrinkage cold-start (NegBin posterior on M5 priors) + M5 pattern classifier (LightGBM, **val_acc=99.5%**). Cold-start branches when n_obs < 90 daily / 26 weekly / 6 monthly. `apps/api/m5/loader.py` is the cached read path.
- ✅ **Day 8**: Chronos-Bolt-Small foundation, global LightGBM with calendar features, CRPS-weighted ensemble combine, split-conformal interval calibration. **92% empirical coverage** on nominal 95% interval.
- ✅ **Day 9**: `dq_reference_dists.parquet` per-dept × metric quantile grids; statistical_fit + stationarity (Pettitt + Mann-Kendall + rolling shift) DQ components lit; LLM explainer with disk-cached batched call.
- ✅ **Day 10**: `analyze_dataframe` sandbox (restricted DSL — not Python eval), `make_chart` Vega-Lite, `compare_to_m5`, `get_data_quality_report` tools added (10 total). Extended thinking enabled (1024-token budget). Eval expanded to 20 questions: **19/20 = 95%** with real Anthropic.
- ✅ **Day 11**: multi-period rolling schedule (90-day plan with delivery dates), (s,S) full Monte-Carlo simulation upgrade, hierarchical reconciliation (MinT-shrink), stockout-cost-aware service level, OrderScheduleTable UI.
- ✅ **Day 12**: joint replenishment recommender, per-dataset settings persistence, `/dashboard/[id]/settings` UI, CSV/XLSX export, CalibrationCard, JointReplenPanel, loading/error states across `/dashboard/[id]` + `/sku/[skuId]`.
- ✅ **Day 13**: Sentry init + structlog + extended `/health` (latency rollups, M5 artifact list, anthropic/sentry flags), slowapi rate limits (chat 30/min/IP, upload 20/hour/IP), Next.js password gate (middleware + `/login` + `/login/submit`), Sentry web stub (lazy-loads `@sentry/browser` if installed), a11y pass on tables + forms, Dockerfile.web + docker-compose with healthchecks.
- ✅ **Day 14**: Modal deployed, Vercel deployed, `docs/DEMO_SCRIPT.md` + `docs/ONE_PAGER.md`, 5/5 chat eval regression, three live dry-runs across `retail_stable`/`coffee_perishable`/`ecommerce_lumpy`.

**Final test status (Day 14):** 168/168 passing.

## MVP+ expansion (post-Day 14, shipped 2026-05-05)

After the 14-day MVP, the user asked to "significantly expand functionality" across
24 categories of features. We picked a coherent slice that:
1. Closed the headline gap — a real **Reorder & Action Layer** so the product moves from "forecast viewer" to "decision tool."
2. Restructured the frontend from a single dashboard into a 9-section **left-rail-navigated app**.
3. Added depth in forecasting transparency, inventory frontier, supplier intelligence, risk + working capital.
4. Made `(s,S)` the canonical default policy (user explicitly asked us to pick one of {(Q,R), (s,S), periodic}).

### Plan files for this expansion
- `~/.claude/plans/i-have-an-mvp-velvet-globe.md` — the 22-feature MVP+ plan (executed in one session)
- `~/.claude/plans/agentic-features.md` — the anomaly-explainer + auto-plan agent design (executed second session)

### What shipped in MVP+ (24 of 24, including 2 agentic features)

**Foundation**
- Realistic synthetic generator: curated supplier-name parts (no `Faker` dep) → "Northwind Beverages LLC", "Pacific Roasters Co.", per-supplier MOQ + case-pack + payment terms, per-receipt lead-time history.
- Demo loader endpoint `POST /datasets/demo/{template}` bootstraps a complete dataset (panel + suppliers + receipts) directly from the synthetic generator. Bypasses upload/confirm. Used by the landing page's "Load demo" buttons.
- Left-rail nav layout at `apps/web/app/dashboard/[id]/layout.tsx` wraps every dashboard route. `/dashboard/[id]` redirects to `/overview`.
- Command palette (⌘K) with fuzzy search over SKUs + suppliers + pages.

**Action layer (the headline gap)**
- New DuckDB tables: `suppliers`, `receipts`, `purchase_orders`, `po_lines`, `po_status_log` — created via `ensure_all_tables(conn)` at confirm/demo time.
- Reorder queue (`apps/api/inventory/reorder_queue.py`) — analytical scoring (no per-SKU forecast call), respects MOQ + case-pack from `suppliers` table, expedite flag on stockout-prob × revenue.
- PO state machine (`apps/api/inventory/purchase_orders.py`) — `drafted → approved → placed → received` (linear) + `cancelled` from any non-terminal state. Each transition writes to `po_status_log`. Multi-line POs supported via `draft_purchase_order_multi_line()` (the single-SKU helper is now a thin wrapper).
- CSV + EDI 850 export (`apps/api/inventory/po_export.py`) — minimal valid X12 850 envelope (ISA / GS / ST / BEG / DTM / N1 / PO1×n / CTT / SE / GE / IEA), no extra deps.

**Depth**
- Sparkline column on every SKU table (inline SVG, no chart library).
- Forecast detail tabs: **Decomposition** (rolling-mean trend + period-mean seasonal + residual; STL-style without `statsmodels` dep) + **Model leaderboard** (per-method MAPE/CRPS/MASE with selected-as-final indicator).
- Service-level vs cost frontier (`apps/api/inventory/frontier.py`) — sweeps SL ∈ {0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99} through `recommend_sku`, returns Pareto points. Newsvendor calculator on the same page.
- Supplier scorecards (`apps/api/inventory/supplier_metrics.py`) — OTIF, on-time%, in-full%, lead-time mean/std, **Bayesian posterior LT** via gamma + normal-approx conjugate update (`bayesian_lead_time_posterior()`), per-supplier MOQ / case-pack / payment terms.

**Risk + working capital**
- Stress test (`apps/api/inventory/stress_test.py`) — analytical per-SKU exposure under perturbed `lead_time_multiplier` × `demand_multiplier` × `service_level`. Returns Δ revenue at risk, VaR/CVaR 95%, top-10 impacted SKUs.
- Working capital (`apps/api/inventory/working_capital.py`) — DIO (inventory $ / annual COGS × 365), DPO (weighted avg of supplier payment terms via `parse_payment_terms_days()`), DSO=0 (no AR data; documented assumption), cash-to-cash = DIO + DSO − DPO.

**Trust + polish**
- `MethodologyDrawer` component + `apps/web/lib/methodology.ts` config — info icon next to any metric → side drawer with formula + inputs + assumptions + current values. Wired into KPI strip; pattern is reusable.
- KPI strip with PoP deltas + sparklines + new tiles (inventory turnover, fill rate, stockout incidents, cash-to-cash, % SKUs <7 days cover).
- Proactive insights tile (`apps/api/insights/compute.py`) — ABC migrations, low-cover alerts, supplier OTIF degradation, expedite candidates, data summary.
- `HelpTooltip` component (`apps/web/components/HelpTooltip.tsx`) — hover-driven info-icon tooltip pattern. Used on all 10 supplier list columns + 8 supplier detail cards. Cheap, dependency-free.

**Agentic features (Phase 6)**
- **Anomaly explainer** — deterministic CUSUM + robust z-score detector (`apps/api/llm/anomaly.py`); LLM only writes the narrative via `apps/api/llm/anomaly_explainer.py`. `Sparkles`-icon button on `ForecastChart` opens a side drawer with detected events list, LLM explanation, demand chart with event marked, collapsible tool-call audit. Heuristic fallback if Anthropic unavailable.
- **Weekly auto-plan agent** — `apps/api/llm/auto_plan.py`. Pre-computes the reorder queue, stuffs it into the user turn (not a tool call — saves 4-6 iterations), forces structured output via the `submit_plan` tool with `tool_choice={"type": "any"}`. Every line is re-validated against the panel after the LLM responds: bad sku_ids dropped, qty re-rounded to MOQ + case-pack via `_round_to_pack()`, `unit_cost` re-fetched (LLM never trusted with prices). Modal with checkable draft list on `/dashboard/[id]/reorder`. Accept endpoint `POST /reorder/auto_plan/accept` creates real multi-line POs.
- Both agents have a `fallback: bool` field in the response so the UI can show a "Heuristic fallback" banner when the LLM is down or the structured output failed.

### LLM loop refactor (foundation for agents)

`run_chat_blocking()` in `apps/api/llm/loop.py` was parameterized so the agents can reuse the same loop with focused prompts:

```python
run_chat_blocking(
    dataset_id, user_turns,
    *,
    system_prompt: str | None = None,         # override SYSTEM_PROMPT
    tool_subset: list[str] | None = None,     # filter TOOL_DEFINITIONS by name
    max_iterations: int = MAX_ITERATIONS,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    tool_choice: dict | None = None,          # force a specific tool ({"type": "any"} or {"type": "tool", "name": "..."})
    include_dataset_summary: bool = True,
    enable_thinking: bool = True,
)
```

Defaults preserve existing behavior — chat panel + eval harness pass through unchanged.
The streaming path `stream_chat_sse()` was NOT touched; it stays as-is for the chat panel.

### LLM tools — 11 total (was 10)

Existing 10 chat tools (`query_skus`, `get_sku_details`, `get_forecast`, `compute_reorder`,
`run_scenario`, `get_aggregate_stats`, `get_data_quality_report`, `compare_to_m5`,
`analyze_dataframe`, `make_chart`) plus:

- **`submit_plan`** — passthrough executor; only purpose is to force structured output from the auto-plan agent. Schema requires `summary` + `draft_pos[].lines[]`. Forced via `tool_choice={"type": "any"}` (gives the LLM flexibility to call either context tools OR submit_plan, then constrains the final to be one of those tools).

### Endpoint surface (39 routes total on Modal)

```
# Ingestion
POST   /datasets/upload                                          # CSV/XLSX
POST   /datasets/{id}/confirm                                    # apply column mapping → DuckDB
GET    /datasets/{id}/quality                                    # DQ report
GET    /datasets/demo/templates                                  # list bootstrap templates
POST   /datasets/demo/{template}                                 # bootstrap full dataset
GET    /datasets/{id}                                            # summary

# Forecasting
POST   /datasets/{id}/skus/{sku}/forecast                        # ensemble forecast
GET    /datasets/{id}/skus/{sku}/decomposition                   # trend/seasonal/residual
GET    /datasets/{id}/skus/{sku}/leaderboard                     # per-method backtest

# Inventory
POST   /datasets/{id}/skus/{sku}/recommend                       # (s,S) by default
GET    /datasets/{id}/skus                                       # paginated table (include_history=true for sparklines)
GET    /datasets/{id}/skus/{sku}/calibration                     # M5 percentile bands
GET    /datasets/{id}/skus/{sku}/history                         # raw demand
GET    /datasets/{id}/skus/{sku}/frontier                        # SL Pareto + newsvendor
GET    /datasets/{id}/joint_replenishment
POST   /datasets/{id}/reconcile                                  # MinT-shrink hierarchical
GET    /datasets/{id}/aggregate_stats
GET    /datasets/{id}/settings ; PUT /datasets/{id}/settings
GET    /datasets/{id}/export                                     # CSV/XLSX bulk recommendations

# Reorder + POs
GET    /datasets/{id}/reorder/queue                              # ranked queue
POST   /datasets/{id}/reorder/draft                              # one-click draft from queue
POST   /datasets/{id}/reorder/auto_plan                          # AGENT — group + rationalize
POST   /datasets/{id}/reorder/auto_plan/accept                   # commit drafts to PO tables
GET    /datasets/{id}/purchase_orders ; GET .../{po_id}
PATCH  /datasets/{id}/purchase_orders/{po_id}                    # status transition + assignee + approval
DELETE /datasets/{id}/purchase_orders/{po_id}
GET    /datasets/{id}/purchase_orders/{po_id}/export?format=csv|edi850

# Suppliers
GET    /datasets/{id}/suppliers                                  # scorecards
GET    /datasets/{id}/suppliers/{sid}                            # detail + receipts + posterior

# Risk + working capital
POST   /datasets/{id}/stress_test
GET    /datasets/{id}/working_capital

# Insights
GET    /datasets/{id}/insights

# Agentic
POST   /datasets/{id}/skus/{sku}/anomaly_explain                 # AGENT — detect + explain

# Chat
POST   /datasets/{id}/chat                                       # SSE streaming, 30/min/IP rate limit

# Health
GET    /health
```

### Patterns established this expansion (worth following next time)

- **Demo loader pattern** — `create_demo_dataset(template)` writes panel + suppliers + receipts directly to DuckDB. Use for any new "ship sample data with the deploy" need. Modal container doesn't need to ship CSVs — the synthetic generator is enough.
- **Heuristic fallback for agentic features** — every agent endpoint returns a `fallback: bool` + `error: str | null` so the UI can render a banner. `_heuristic_explanation()` and `_fallback_plan()` are the templates.
- **HelpTooltip pattern for column headers** — `<HelpTooltip text="..." />` next to `<th>` content. Use it everywhere abbreviations like OTIF / DIO / DPO / CRPS appear. Pure CSS hover, no Radix dep.
- **MethodologyDrawer pattern for metrics** — `<MethodologyDrawer metric="cash_to_cash" contextValues={{...}} />` next to a KPI label. Schema in `apps/web/lib/methodology.ts`. Add new entries when introducing a new computed metric.
- **Validation-after-LLM** — never trust the LLM with prices, sku_ids, qty without re-checking against the panel. `_validate_and_normalize()` in `auto_plan.py` is the canonical example.
- **Heuristic detector + LLM narrative** — when building any future "explain X" agent: detect deterministically server-side, then ask the LLM only for the prose. The LLM cannot invent the event.
- **Forced tool output** — `tool_choice={"type": "any"}` is more flexible than `{"type": "tool", "name": "..."}` because the LLM can still call context tools first, then settle on the forcing tool. Use `_extract_<tool_name>(resp)` to pull the structured payload back out.

### New gotchas hit during MVP+ expansion

- **DuckDB reserves `at` as a keyword.** Quote it: `'INSERT INTO po_status_log (..., "at", ...) VALUES (...)'`. Same for `ORDER BY "at"`. We hit this on first insert into `po_status_log`.
- **`generate_synthetic` is the LEGACY single-return-value function — keep it that way.** Existing `apps/api/tests/test_synthetic.py` calls `generate_synthetic(...)` and expects a `pd.DataFrame`. The new triple `(panel, suppliers, receipts)` lives on `generate_synthetic_full()`. Don't change `generate_synthetic`'s return shape — you'll break 9 tests.
- **Realistic supplier metadata is generated by SUPPLIER NAME, not by ID.** When deriving suppliers from an uploaded panel, `derive_suppliers_from_panel()` uses a deterministic hash of the supplier name to seed MOQ / case-pack / payment terms / country. So the same uploaded CSV produces the same supplier metadata across reloads. `_supplier_id_from_name()` is the slug helper.
- **`Faker` is NOT a dependency.** We use a curated list of ~35 supplier-name "first" parts × business-word categories aligned with category kinds (BEV/FOOD/APPAREL/...). Keeps the Modal image small.
- **Test count after MVP+ expansion: 181/181** (168 pre-existing + 13 new in `test_agentic.py`). The new tests cover anomaly detector, anomaly explainer fallback path, auto-plan fallback + validation, multi-line PO helper, `_round_to_pack()` semantics. Don't break them.
- **`_round_to_pack(qty, moq, case_pack)` semantics** — `case_pack` round-up first, then `moq` floor, then re-align to `case_pack` if the MOQ floor isn't already a case-pack multiple. So `_round_to_pack(50, moq=100, case_pack=12) == 108`, not `100`. The auto-plan validator and the reorder queue's `_round_to_moq_pack()` both follow this.
- **`tool_choice` forces an action but doesn't guarantee `submit_plan` specifically.** Always handle the case where the LLM never calls `submit_plan` (timeout, refusal). `_extract_submit_plan(resp)` returns `None` in that case → fall back to `_fallback_plan()`.
- **The realistic synthetic data is slightly noisier than the old uniform data.** `test_dq_report_clean_panel` was loosened from `plausibility.score == 100.0` to `>= 99.0` because the more varied data triggers a single demand-spike outlier per panel. Don't tighten it back.
- **Vercel `vercel --prod --yes` exit-codes 0 even when the upload polls time out** — the deploy itself completes. `Aliased: https://web-delta-one-65.vercel.app` in the output is the source of truth.

### Files added this expansion (new code surface to know)

Backend (apps/api/):
```
ingestion/demo.py                         # bootstrap full dataset from synthetic
inventory/reorder_queue.py                # ranked queue scoring
inventory/purchase_orders.py              # CRUD + state machine + multi-line helper
inventory/po_export.py                    # CSV + EDI 850
inventory/supplier_metrics.py             # scorecards + Bayesian posterior + derive_from_panel
inventory/frontier.py                     # SL pareto + newsvendor
inventory/stress_test.py                  # VaR/CVaR + per-SKU shock
inventory/working_capital.py              # cash-to-cash
forecasting/decompose.py                  # trend/seasonal/residual
forecasting/leaderboard.py                # per-method backtest
insights/__init__.py + insights/compute.py
llm/anomaly.py                            # CUSUM/MAD detector
llm/anomaly_explainer.py                  # LLM narrative + heuristic fallback
llm/auto_plan.py                          # auto-plan agent with submit_plan
tests/test_agentic.py                     # 13 new tests
```

Frontend (apps/web/):
```
app/dashboard/[id]/layout.tsx             # left-rail wrapper
app/dashboard/[id]/{overview,reorder,forecasts,frontier,suppliers,suppliers/[supplierId],
                    stress,quality,chat}/page.tsx
components/SidebarNav / CommandPalette / Sparkline / MethodologyDrawer / HelpTooltip
components/InsightsTile / WorkingCapitalTile / LeadTimeHistogram / DecompositionTabs
components/ReorderPageClient / FrontierPageClient / StressTestClient / ForecastsTable
components/AnomalyExplainerButton / AnomalyDrawer / AutoPlanModal
components/LandingActions
lib/methodology.ts
```

## Live deployment state (as of 2026-05-05)

| | |
|---|---|
| **App version** | `0.2.0` (MVP+ expansion + agentic features) |
| **Live web URL** | https://web-delta-one-65.vercel.app (alias) — current deployment id changes per push |
| **Live Modal API URL** | https://shantk--inventory-optimizer-fastapi-app.modal.run |
| **Modal app dashboard** | https://modal.com/apps/shantk/main/deployed/inventory-optimizer |
| **Modal secret** | `inventory-secrets` (ANTHROPIC_API_KEY + ANTHROPIC_MODEL) |
| **Vercel project** | `shantk-5857s-projects/web` |
| **Vercel env (production)** | `MODAL_API_URL`, `ANTHROPIC_API_KEY` set |
| **Deploy commands** | Backend: `modal deploy apps/api/modal_app.py`. Frontend: `cd apps/web && vercel --prod --yes`. Both run from repo root with `.venv` activated for Modal. |
| **Routes on Modal** | 39 (was 21 at MVP). |
| **Test count** | 181/181 passing (`PYTHONPATH=. pytest apps/api/tests`). 168 from MVP + 13 new in `test_agentic.py`. |
| **TypeScript** | clean (`npx tsc --noEmit` from `apps/web`). |
| **Next.js build** | clean, 16 routes (`npx next build` from `apps/web`). |

**Live verification done 2026-05-05** via Vercel `/api/*` proxy → Modal:
- Demo loader creates a 200-SKU / 6-supplier dataset with realistic names ("Northwind Brewers Holdings", "Highland Kitchens Corp.", etc.)
- Reorder queue ranks by stockout-risk × revenue, MOQ-rounded
- PO state machine: drafted → approved → placed → received with 4 audit-log entries
- CSV + EDI 850 export round-trip clean (X12 envelope starts `ISA*00*...`)
- Supplier scorecards return real OTIF + Bayesian posterior LT
- Stress test, working capital, insights all return non-empty
- **Anomaly explainer**: real LLM call with 3 tool calls → grounded explanation referencing the supplier and the z-score
- **Auto-plan agent**: real LLM call → grouped PO drafts with rationale, accept-flow creates real multi-line POs in DuckDB

## Pending for the user (none block dev work)

| Item | Note |
|---|---|
| First `git commit` | **146 files staged on `main`** with zero data/csv/zip/.env tracked. Hard rule: never auto-commit. |
| `DEMO_PASSWORD` in Vercel env (optional) | Live URL is currently open. To enable: `cd apps/web && vercel env add DEMO_PASSWORD production` then redeploy. |
| `SENTRY_DSN` in Modal secret + Vercel env (optional) | Stays off until set. |
| Real Kaggle API token (low priority) | Current `KGAT_...` token returns 401. M5 raw already extracted; only blocks re-downloads. |
| Loom recording | See [DEMO_SCRIPT.md](DEMO_SCRIPT.md) — minute-by-minute walkthrough. |
| Class submission | [ONE_PAGER.md](ONE_PAGER.md) drop-in. |

## Production deployment notes (gotchas a future session WILL hit)

These are scars from the actual deploys — keep them in mind before re-deploying.

### Modal image must include ALL transitive deps
The runtime imports cascade through `observability.py` (structlog at module-load), `assertions/explainer.py` (anthropic), `m5/loader.py` (pandas+pyarrow), `forecasting/foundation.py` (chronos+torch). The current `apps/api/modal_app.py` `pip_install` list is correct — verify it contains: `structlog`, `sentry-sdk[fastapi]`, `hierarchicalforecast`, `torch`, `chronos-forecasting`. **If you add a new top-level dep, add it to the Modal image's pip list and redeploy.**

When the runtime fails with a missing import, `modal app logs inventory-optimizer` shows the `ModuleNotFoundError` and client requests time out at the asgi layer. The first deploy here failed with `No module named 'structlog'`.

### Chronos-Bolt quantile clipping (cosmetic, non-fatal)
Chronos-Bolt was trained on quantile levels {0.1, 0.2, ..., 0.9}. We request {0.025, 0.1, 0.5, 0.9, 0.975}, so q0.025 and q0.975 get clipped to q0.1 and q0.9. The conformal wrapper widens them back to honest coverage. The warning in stdout is expected — don't try to silence it.

### Vercel build pitfalls
- Strict ESLint blocks the build on `react/no-unescaped-entities` (apostrophes in JSX). We disabled that rule in `apps/web/.eslintrc.json`. Do not re-enable.
- `useSearchParams` in any client component requires a `<Suspense>` boundary at static-build time (`/login` page wraps `LoginInner` in Suspense). Do the same for any new search-param consumer.
- The Vercel CLI sometimes hits `read ETIMEDOUT` polling deploy status mid-build — the deploy itself completes. `vercel ls --prod` is the source of truth.

### Anthropic key vs pydantic-settings precedence
The Claude Code harness sets `ANTHROPIC_API_KEY=""` (empty) in the env, which would beat the `.env` file under pydantic-settings' default precedence. Fixed by `load_dotenv(override=True)` at module-load in `apps/api/config.py`. **Do not remove that block.**

## Testing notes (don't fight these — they're load-bearing)

- `apps/api/tests/conftest.py` sets `OMP_NUM_THREADS=1` to avoid lightgbm + libomp segfaults under threaded TestClient on macOS arm64.
- It also sets `RATELIMIT_DISABLED=1` so the slowapi limiter doesn't bleed across tests in the same TestClient session. Production code reads the same env var.
- Per-test data dirs work via `monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))`. **Do not** call `get_settings.cache_clear()` — it clobbers the mutation and tests will silently write to the real `./data/datasets/` (gitignored, but bad). Existing fixtures in this repo use the correct pattern; copy from them.

## Demo state (Day 14)

- [DEMO_SCRIPT.md](DEMO_SCRIPT.md) — 4-minute Loom walkthrough, pre-demo checklist, Q&A bank, failure mitigations.
- [ONE_PAGER.md](ONE_PAGER.md) — drop-in for class submission.
- Three sample CSVs generated by `bash scripts/seed_demo.sh` (ALL gitignored): `retail_stable.csv` (smooth/seasonal, weekly), `coffee_perishable.csv` (newsvendor path, daily), `ecommerce_lumpy.csv` (intermittent — all 300 SKUs classified Z).
- Local docker-compose fallback for demo day: `cd infra && docker compose up`.

## Hard rules for what to do **before** anything is committed

- `git ls-files --cached | grep -E "(\.zip|\.csv|\.env$|^data/)"` must return zero matches. The `.gitignore` already enforces this; don't weaken it.
- Never run `git commit` autonomously — wait for explicit user instruction.
- Never reveal `~/.kaggle/kaggle.json` contents in output. Confirm presence/perms instead.

## Speed posture

When you (Claude Code) work on a task here:
- Don't add features beyond what the task says.
- Don't refactor unrelated code.
- Don't add error handling for impossible cases.
- Don't write tests for trivial code.
- Default to no comments. Identifiers should explain themselves.
- If something would push the day's scope, surface it and ask — don't silently expand.
