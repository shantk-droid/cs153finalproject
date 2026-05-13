# CLAUDE.md — durable context for this project

Project: an inventory-optimizer monorepo. Next.js web (`apps/web`) + FastAPI API
(`apps/api`) + M5 Walmart calibration artifacts (`apps/api/m5/artifacts/`).
Two-service architecture: web on Vercel, API on Modal. Each plays a different
role; updates need to land in both places.

---

## Working preferences

These are durable instructions for Claude on this codebase, migrated from
auto-memory on 2026-05-05. They replace the prior
`~/.claude/projects/.../memory/` entries.

### Plan revision authority

When something in the original plan, outline, or phasing I committed to seems
wrong or sub-optimal mid-execution, **revise the order/scope and continue** —
don't ask for permission on every order change. The user explicitly authorized
this on 2026-05-04.

**Why:** The user wants speed without sacrificing quality. Asking for
permission on every order change slows them down; they trust my judgment as
long as I'm explicit about the change.

**How to apply:**
- Make the revision and proceed.
- Surface the revision in the response: what changed, why, and what now lands
  when.
- Update the plan file or todo list to reflect the new order so it stays the
  source of truth.
- Don't revise silently — they want to see what I'm thinking.

### Defer user-blocked tasks

Continue autonomous work as long as possible; only stop when a task literally
cannot proceed without the user. Defer anything that needs user-only
credentials (Anthropic API key, Modal/Vercel auth, Kaggle tokens, native
installs like `libomp`) and keep building everything else.

**Why:** The user is solo and time-bounded. They explicitly said "defer these
unless I'm necessary" on 2026-05-04. Stopping to wait wastes their time.

**How to apply:**
- Surface which tasks are user-blocked and which I'm proceeding with.
- Order autonomous work first; the list of blockers stays at the end of the
  response.
- Don't wait for permission to keep going — the standing direction is "keep
  going."
- For credentials specifically: don't write code that would silently 401 if the
  key is missing. Either stub gracefully (return empty / fall back to
  heuristic) or skip.

---

## Outstanding work (snapshot 2026-05-13)

Read this first when picking up the project — it's the priority queue, sorted
by who can move each item forward. Update / prune as items land.

### User-only (blocked on credentials or approvals)

1. **Add `SENTRY_DSN` to the `inventory-secrets` Modal secret.** Code path
   is wired (`observability.init_sentry`); dormant until the secret is set.
2. **Add `ANTHROPIC_API_KEY` to GitHub repo secrets.** Unblocks the
   `agent-eval` job in `.github/workflows/ci.yml`.
3. **Decide on GPU access** if you want the research-track items below.
   1.7 Chronos LoRA is the highest-leverage; A10 GPU on Modal, ~$2-5/run.

### Highest leverage if I keep shipping

- **Run the agent task suite end-to-end** against a real dataset with API
  key. The 30 tasks in `evals/agent_tasks.yaml` have only been validated
  structurally — the LLM-as-judge pass rate hasn't been measured. ~$0.50,
  ~10 min. Output is the headline pass-rate number for the writeup.
- **Forecast benchmark on M5 held-out slice (5.1 deferred).** Compare
  Croston / classical / classical + Chronos / full ensemble / + conformal
  / + LLMTime on WRMSSE / MASE / pinball. ~3 days. Produces the headline
  bar chart for the writeup. Existing `apps/api/forecasting/backtest.py`
  is the foundation; `evals/forecast_benchmarks.py` is a stub to extend.
- **3.2 SKU features perf**: `ml.py:_build_design_matrix` is ~5 min slow
  on a 200-SKU panel on first run because every unique SKU gets a fresh
  Haiku call. Two fixes: (a) parallelize via `concurrent.futures` (~3x,
  ~30 min); (b) batch into a single Haiku call with one tool emission
  per SKU (~10x, ~2h). Cache covers subsequent calls, but first-run UX
  on a new dataset is the bottleneck.

### Research track — CPU-only (no GPU needed)

- **1.2 Stacking meta-learner** — LightGBM on out-of-fold pinball losses
  → per-(SKU, horizon) ensemble weights. Wires into `ensemble.py`'s
  `crps_weights()` as a `weights_meta` source. ~2 days.
- **1.6 Hierarchical Bayesian** — NumPyro NUTS on CPU. Replaces
  `bayes.py`'s closed-form Poisson/Gamma with SKU < Category <
  Department partial pooling. ~3 days.
- **1.8 MDN demand head** — small MLP that takes ensemble output and
  emits a 3-component NegBin mixture. ~2 days.
- **1.9 Bayesian lead-time per (supplier, SKU)** — hierarchical Gamma
  priors, posterior update from receipt history; surfaced on the
  supplier scorecard. ~2 days.
- **1.12 Probabilistic hierarchical reconciliation** — upgrade from
  MinT-shrink (point) via `hierarchicalforecast` library. ~2 days.

### Research track — GPU needed (user approval first)

- **1.7 Chronos LoRA fine-tune** — A10 GPU on Modal, ~2h, $2-5. Train a
  parameter-efficient LoRA adapter on M5 retail (5K SKUs × 1.9K days).
  Output is `chronos_lora_retail.pt` (<10 MB) that ships with M5
  artifacts and wires into `forecasting/foundation.py`. Strongest "we
  trained" research-track story.
- **1.11 N-BEATS-Interpretable** — GPU helpful, CPU OK. Replaces /
  augments `forecasting/decompose.py` STL with deep-learning
  decomposition.

### Smaller polish

- **5.3 Coverage diagnostics admin page** — visualize empirical conformal
  coverage per (horizon, level, profile). ~1 day. The data is already
  produced by `_per_horizon_coverage`; just needs a frontend page.
- **3.10 Extended thinking surfacing** — `enable_thinking=True` exists on
  `run_chat_blocking`. Surface the reasoning chain in the agent lane
  (collapsible). ~1 day.

### Operational debt

- **`evals/agent_tasks.yaml` pass-rate baseline**: run it 3 times and
  record the multi-agent pass rate before declaring the 75% CI threshold
  binding. LLM-as-judge has ~5-10% run-to-run variance.
- **3.2 perf fix** (see above).

### Default when nothing else is specified

The natural next step is **"run the agent task suite + forecast
benchmark."** That's what turns the multi-agent system from "built" into
"measured" — and produces the headline numbers for the writeup. If the
user mentions Chronos LoRA, switch to that instead.

---

## Deployment topology

This project has **two services that must be deployed separately**. The web
proxies all `/api/*` requests through `MODAL_API_URL` to the Python backend.
A common failure mode is "I deployed Vercel and the site is broken" because
Modal still has the old API contract.

### Web (Vercel)

- **Production URL:** https://web-delta-one-65.vercel.app
- **Project:** `shantk-5857s-projects/web` (vercel CLI authenticated as
  `shantk-5857`)
- **Linked dir:** `apps/web/.vercel/`
- **Required env vars** (set in Vercel project, both encrypted):
  `MODAL_API_URL`, `ANTHROPIC_API_KEY`
- **Deploy:**
  ```bash
  export PATH="/Users/shantkoutnouyan/.nvm/versions/node/v20.20.2/bin:$PATH"
  cd apps/web && npx --yes vercel@latest deploy --prod --yes
  ```

### API (Modal)

- **Production URL:** https://shantk--inventory-optimizer-fastapi-app.modal.run
- **App name:** `inventory-optimizer`
- **Modal CLI:** `/Library/Frameworks/Python.framework/Versions/3.12/bin/modal`
  (already authenticated)
- **Secret:** `inventory-secrets` (carries `ANTHROPIC_API_KEY`)
- **Persistent volume:** `inventory-optimizer-data` mounted at `/root/data`
- **Deploy:**
  ```bash
  /Library/Frameworks/Python.framework/Versions/3.12/bin/modal deploy apps/api/modal_app.py
  ```

### When to redeploy what

| Touched files                                | Redeploy             |
|-----------------------------------------------|----------------------|
| `apps/web/**`                                 | Vercel only          |
| `apps/api/**` (routes, schemas, scoring, etc.)| Modal **and** Vercel if any TS types changed |
| `apps/api/profiles/data/*.json`               | Modal only           |
| `apps/api/m5/artifacts/*`                     | Modal only           |

After a Modal-only deploy, smoke-test with:
```bash
curl -s https://shantk--inventory-optimizer-fastapi-app.modal.run/datasets/profiles | head -c 200
curl -s https://shantk--inventory-optimizer-fastapi-app.modal.run/datasets/demo/templates | head -c 200
```

### Smoke-test prod end-to-end (when "demo doesn't work for X" is reported)

The deployed flow is: browser → Vercel proxy → Modal. Run all four; all
should return 200. Anything else points at the layer to fix.

```bash
# 1. Vercel env vars set?
export PATH="/Users/shantkoutnouyan/.nvm/versions/node/v20.20.2/bin:$PATH"
cd apps/web && npx --yes vercel@latest env ls
# Expect MODAL_API_URL and ANTHROPIC_API_KEY (Encrypted, Production+Preview).

# 2. Health endpoint reachable end-to-end via the proxy?
curl -sS https://web-delta-one-65.vercel.app/api/health

# 3. Demo POST works end-to-end?
curl -sS -X POST https://web-delta-one-65.vercel.app/api/datasets/demo/coffee_perishable

# 4. SSR dashboard page renders for the new dataset?
DSID=$(curl -sS -X POST https://web-delta-one-65.vercel.app/api/datasets/demo/coffee_perishable | python3 -c "import json,sys; print(json.load(sys.stdin)['dataset_id'])")
curl -sS -o /dev/null -w "%{http_code}\n" "https://web-delta-one-65.vercel.app/dashboard/${DSID}"
```

If a user still reports failure after all four return 200, ask them to:
- Click "Copy diagnostic" on the error toast (LandingActions captures
  status / response body / userAgent / template / timestamp).
- Share the JSON blob; reproduce locally from those inputs.

---

## Local dev

```bash
# One-shot for both servers (script's `python` check requires venv activation):
PYTHONPATH=$PWD .venv/bin/uvicorn apps.api.main:app --port 8000 --reload &
export PATH="/Users/shantkoutnouyan/.nvm/versions/node/v20.20.2/bin:$PATH"
npm run dev:web &
```

Web on http://localhost:3000, API on http://localhost:8000 (`/health`,
`/docs`). The web's API proxy falls back to `http://localhost:8000` when no
`MODAL_API_URL` is set.

Backend tests: `.venv/bin/python -m pytest apps/api/tests/` (188 tests, ~100s).
Frontend typecheck: `npm run typecheck` from `apps/web`.

---

## Architecture notes (non-obvious)

### Reference profile system (data quality)

Distribution-fit scoring runs against one of five named profiles (retail_m5,
ecommerce_fashion, b2b_industrial, pharma_medical, spare_parts_mro), not the
hardcoded M5 reference. Profiles live in `apps/api/profiles/data/*.json` and
are loaded once at import via `apps.api.profiles.registry._load_all` (LRU
cached). Scoring is **soft penalty** based on p2/p10/p90/p98 percentiles per
metric — there is no hard pass/fail.

Per-dataset profile selection is stored as a sidecar JSON at
`{data_dir}/metadata/{dataset_id}.json` (matches the existing
`apps/api/ingestion/storage.py` upload-metadata pattern). On read miss, the
loader falls back to `profile_id = "retail_m5"` for backwards compat with
older datasets.

### Lazy DQ rescore

`GET /datasets/{id}/quality` auto-detects legacy reports (component name
`statistical_fit`, missing `profile`, or assertion code
`STATISTICAL_ANOMALY_VS_M5`) and rebuilds them from the panel data on the fly.
This means upgrading the scoring code doesn't require a backfill — every old
dataset migrates lazily on first view.

### SKU triage status

`SkuTableRow.status` is computed by a **lightweight heuristic** in
`apps.api.inventory.status.derive_status` (compares days-of-cover against lead
time × {1.0, 1.5, 2.0}). It deliberately does *not* invoke the recommend
pipeline per row — that would be O(N) full forecasts on the list endpoint.
The richer status (using the actual `(s, S)` reorder point) is derived
front-end-side from `Recommendation` on the SKU detail page via
`@/lib/sku-status:derivePresentationStatus`.

### LLM insights graceful fallback

`apps/api/llm/insights.py` has three orchestrators (panel / supplier / sku).
Each one returns `[]` / `None` when `ANTHROPIC_API_KEY` is empty, when the API
errors, or when the model output fails to parse. The frontend
`LlmInsightsPanel` and `SkuNarrativeCard` render heuristic insights instantly,
fire the LLM call lazily, and merge results when they arrive. If the LLM
returns nothing, the heuristics stay — no error UI, no flicker. Keep this
pattern when adding new LLM-enriched UI.

Cache: keyed by sha256 of the JSON-serialized context, stored under
`{data_dir}/llm_insights/`. Repeat dashboard visits cost $0.

### REST endpoints lifted from chat tools

Two endpoints were lifted out of the chat-tool layer so the SKU detail page
can render without an LLM round-trip:

- `POST /datasets/{id}/skus/{sku}/decompose` → wraps
  `apps.api.forecasting.decompose.decompose_sku`
- `POST /datasets/{id}/skus/{sku}/scenario` → wraps
  `apps.api.inventory.recommend.recommend_sku` and returns
  `{base, scenario, deltas}`

Both still work as chat tools too — same underlying functions.

### Conformal coverage is per-horizon

`Forecast.conformal_coverage` is a **list** of `ConformalCoverage` (one per
horizon × level), not a single number. The forecast.py code samples residuals
at h=1, h=4, h=8, h=12 separately and exposes all available empirical
coverages on the SKU page. Don't collapse this back to a single number — it
was a known bug in the old code. h=8/h=12 only populate when the dataset has
enough history (`backtest_horizon >= 12`); the per-horizon helper silently
skips missing horizons.

### Multi-agent chat (Router / Planner / specialists)

The `/datasets/{id}/chat` route defaults to the multi-agent orchestrator. A
Haiku Router classifies each turn into `single` (existing single-agent loop)
or `multi` (Planner decomposes via `dispatch_specialist` into
Forecaster/Risk/Buyer specialists). Pass `?single=1` to bypass — used by the
eval harness to pin regression coverage.

- `apps/api/llm/orchestrator.py` runs the Planner in a background thread and
  bridges sync→async via `asyncio.Queue` so SSE events stream in real time.
- `apps/api/llm/specialists.py` wraps `run_chat_blocking` with per-specialist
  `system_prompt` + `tool_subset`. **Dispatcher state is stored in
  `threading.local()`** in `executors.py` (`_set_active_dispatcher` /
  `_get_active_dispatcher`) — under concurrent /chat requests, a module
  global would let Planner A end up using Planner B's dispatcher and read
  B's dataset (cross-tenant leak). Keep this thread-local.
- Per-call USD ceiling: `MULTI_AGENT_USD_CEILING = 0.50` in
  `orchestrator.py`; emits `cost_cap_hit` SSE event when reached.
- Daily ceiling: `apps/api/llm/cost_ledger.py` enforces
  `llm_daily_usd_budget`; chat route returns HTTP 429 when exceeded.
- New SSE event types beyond the original four: `router_decision`,
  `agent_start`, `agent_dispatch`, `agent_complete`, `cost_cap_hit`. The
  frontend renders them in an "Agents lane" in `ChatPanel.tsx`.

### NL-to-query SQL allowlist

`apps/api/llm/nl_query.py` lets the agent translate user questions into
read-only DuckDB SELECTs. Defense-in-depth: (a) Haiku-emitted SQL via
forced-tool output, (b) regex-based `validate_sql` rejects banned keywords
(`DROP`, `INSERT`, `ATTACH`, `COPY`, `PRAGMA`, `read_csv`, `glob`,
`information_schema`, CTEs, multi-statement), (c) table-name allowlist
(`panel`, `suppliers`, `skus`) catches subquery FROMs, (d) DuckDB opened
read-only. 16 adversarial tests in `test_nl_query.py` pin the behavior — add
to them if you extend the schema.

### LLMTime forecaster (3.1) — off by default

`apps/api/forecasting/llm_forecaster.py` is an LLM-as-forecaster ensemble
member (Gruver et al. NeurIPS 2023). Disabled by default for cost — turn on
per call via `forecast_sku(..., enable_llm_forecaster=True)` or globally via
the `ENABLE_LLM_FORECASTER=1` env var. Each call is ~$0.001 (Haiku), cached
by (series-hash, horizon) so repeat backtests are free. Quantiles are
normal-approximated from recent-residual sigma; LLMs don't reliably emit
calibrated quantiles, so we don't ask. Wired into the ensemble alongside
classical / chronos / lightgbm — `crps_weights()` decides relative weight.

### LLM-extracted SKU features (3.2)

`apps/api/llm/sku_features.py` labels each SKU on five product-aware
dimensions: `is_perishable`, `is_seasonal`, `discretionary_vs_essential`,
`gift_likelihood`, `weather_sensitive`. Joined into `ml.py`'s LightGBM
design matrix as numeric columns. Cache key is `(category, description)`
sha256 — variant SKUs share the cache hit. Falls back to neutral labels
when no API key is set. **Disable in tests / batch jobs with
`DISABLE_LLM_SKU_FEATURES=1`** — the panel iteration is cheap but the cache
warm-up takes ~5 minutes on 200 SKUs.

### Structured anomaly explanation (3.4)

`apps/api/llm/anomaly_explainer.py` now returns BOTH a free-form narrative
`explanation` AND a structured `judgment` dict with `{cause, confidence,
evidence, suggested_adjustment, source}`. The agent is forced to call
`submit_anomaly_explanation` (a planner-tier tool registered in
`ANOMALY_TOOL_DEFINITIONS`) with constrained enums: cause ∈ {promotion,
holiday_or_calendar, weather_event, supplier_stockout, data_entry_error,
regime_shift, competitive_event, category_wide_trend, unclear};
adjustment ∈ {ignore, investigate_manually, override_forecast,
flag_for_review}. Calendar context (fixed-date US holidays within ±2
weeks of the event) and sibling SKUs (top revenue in the same category)
are pre-computed and threaded into the user prompt so the agent doesn't
need extra tool calls to find them. Heuristic fallback returns both fields
with `source="heuristic"` when the LLM is unavailable.

### Scheduled morning briefing

`apps/api/llm/briefing.py` runs the multi-agent Planner once per dataset
per day. Triggered by `scheduled_briefing` in `modal_app.py`
(Modal `Cron("0 14 * * *")` = 14:00 UTC = ~7am Pacific summer). Cached at
`{data_dir}/llm_insights/briefing.{dataset_id}.{YYYY-MM-DD}.json`. The
dashboard reads via `GET /datasets/{id}/briefing` (returns a stub if
today's file isn't yet generated). Manual refresh via
`POST /datasets/{id}/briefing/refresh`, rate-limited 4/min.

### LLM-narrated dashboard tour

`apps/api/llm/tour.py` generates a 4-step welcome tour per dataset, cached
30 days at `{data_dir}/llm_insights/tour.{dataset_id}.json`. Falls back to
a canned heuristic 4-step tour when LLM unavailable.

### Dark mode tokens

CSS variables in `apps/web/app/globals.css` cover both light and dark. The
`popover` token is needed by `HelpTooltip.tsx` (which uses `bg-popover` /
`text-popover-foreground`); both are wired up, including the corresponding
Tailwind extension in `tailwind.config.ts`. If a tooltip looks transparent in
dark mode, that token isn't being applied.

For disabled-input gray text in dark mode: don't use `<input disabled>` — the
browser forces a fixed gray that ignores CSS variables. Use a styled
display-only span instead (see `Field` component in `FrontierPageClient.tsx`).

---

## File map (the high-leverage ones)

### Backend
- `apps/api/main.py` — FastAPI app + router registration.
- `apps/api/modal_app.py` — Modal deployment config.
- `apps/api/config.py` — `Settings` (env + `.env` loading; loads with
  `override=True` to beat the harness-injected blank `ANTHROPIC_API_KEY`).
- `apps/api/profiles/registry.py` — profile loader, soft-penalty scorer, auto-detect.
- `apps/api/profiles/data/*.json` — five reference profiles.
- `apps/api/assertions/score.py` — composite DQ score; `DEFAULT_WEIGHTS`
  (completeness 0.25, plausibility 0.25, history 0.20, stationarity 0.15,
  distribution_profile 0.15).
- `apps/api/assertions/statistical.py` — soft-penalty distribution-profile
  scoring; also keeps `_matched_dept_row` + `metrics_for_sku` for the legacy
  M5 calibration endpoint.
- `apps/api/ingestion/routes.py` — upload, confirm, quality (with lazy
  rescore), metadata GET/PATCH, profiles list, demo templates.
- `apps/api/ingestion/storage.py` — sidecar metadata JSON + upload temp store.
- `apps/api/ingestion/demo.py` — bootstraps demo datasets; maps template to
  profile via `TEMPLATE_PROFILE`.
- `apps/api/inventory/routes.py` — list SKUs, recommend, scenario, suppliers,
  reorder queue.
- `apps/api/inventory/status.py` — lightweight status heuristic.
- `apps/api/inventory/recommend.py` — orchestrates per-SKU policy choice +
  schedule.
- `apps/api/forecasting/forecast.py` — ensemble + per-horizon conformal +
  audit metadata. New: `enable_llm_forecaster` param wires in LLMTime
  (3.1) when feature flag is on.
- `apps/api/forecasting/conformal.py` — calibration math.
- `apps/api/forecasting/decompose.py` — STL decomposition (REST + chat tool).
- `apps/api/forecasting/llm_forecaster.py` — LLMTime forecaster (3.1).
  Off by default; uses Haiku + forced-tool output for point forecast,
  normal-approx quantiles, sha256 cache.
- `apps/api/forecasting/ml.py` — global LightGBM. Now joins the 5-dim
  LLM SKU features (3.2) onto its design matrix; gate with
  `DISABLE_LLM_SKU_FEATURES=1` in tests.
- `apps/api/ingestion/connectors/shopify.py` — Shopify CSV
  auto-detection + line-item → SKU panel transform. Wired into
  `ingestion/routes.py:upload_dataset`.
- `apps/api/ingestion/sample_data/shopify_sample.csv` — ~500-row demo
  CSV for testing the connector path end-to-end.
- `apps/api/observability.py` — Sentry + structlog + `RequestLoggingMiddleware`.
  The middleware now calls `record_latency(route_template, duration_ms)`
  on every request so `/health` reports real p50/p95 per route.
- `apps/api/llm/routes.py` — `/chat` (SSE, multi-agent by default; `?single=1`
  forces legacy single-agent path) + insights + briefing + tour endpoints.
- `apps/api/llm/insights.py` — LLM enrichment (panel / supplier / sku) with
  caching and graceful fallback. **Pattern reference for every cached LLM
  feature** (sha256 → JSON on disk).
- `apps/api/llm/orchestrator.py` — multi-agent coordinator. Router → Planner
  → specialist sub-agents via threading.Thread + asyncio.Queue.
- `apps/api/llm/router.py` — Haiku classifier. `path: "single"|"multi"`.
- `apps/api/llm/specialists.py` — Forecaster / Risk / Buyer / Planner
  wrappers around `run_chat_blocking` with `system_prompt` + `tool_subset`.
- `apps/api/llm/tools.py` — `TOOL_DEFINITIONS` (chat) + `PLANNER_TOOL_DEFINITIONS`
  (`dispatch_specialist`, `submit_final_answer`) + `ANOMALY_TOOL_DEFINITIONS`
  (`submit_anomaly_explanation`). `ALL_TOOL_DEFINITIONS` is the union that
  `_filter_tools` in `loop.py` searches.
- `apps/api/llm/executors.py` — all executor functions. Dispatcher state is
  `threading.local()` — see "Multi-agent chat" architecture note.
- `apps/api/llm/cost_ledger.py` — daily LLM spend ledger;
  `check_budget` raises `BudgetExceededError` → HTTP 429 in chat route.
- `apps/api/llm/sku_features.py` — 5-dim SKU labeler (3.2).
- `apps/api/llm/llm_forecaster.py` *(NOTE: in forecasting/, not llm/)* —
  LLMTime forecaster (3.1).
- `apps/api/llm/anomaly_explainer.py` — anomaly explainer (3.4). Returns
  both free-form `explanation` and structured `judgment`. Uses
  `submit_anomaly_explanation` forced tool.
- `apps/api/llm/nl_query.py` — NL→DuckDB SELECT with regex SQL allowlist.
- `apps/api/llm/briefing.py` — scheduled morning briefing.
- `apps/api/llm/tour.py` — LLM-narrated 4-step dashboard tour.
- `apps/api/llm/judge.py` + `apps/api/llm/agent_eval.py` + `evals/agent_tasks.yaml`
  — agent task suite with LLM-as-judge for free-form tasks.
- `apps/api/synthetic.py` — Bernoulli–NegBinom intermittent demand generator;
  `TEMPLATES` dict has six templates calibrated to profile centroids.

### Frontend
- `apps/web/app/page.tsx` — landing page with scrolling tab tour.
- `apps/web/app/dashboard/[id]/layout.tsx` — sidebar nav + theme toggle.
- `apps/web/app/dashboard/[id]/page.tsx` — action queue (no longer a redirect).
- `apps/web/app/dashboard/[id]/forecasts/page.tsx` + `ForecastsTable.tsx` —
  header tiles, filters, status pills, sparklines, CSV export.
- `apps/web/app/dashboard/[id]/sku/[skuId]/page.tsx` — header block →
  forecast → schedule → diagnostics → policy/scenario → audit footer.
- `apps/web/app/dashboard/[id]/frontier/page.tsx` + `FrontierPageClient.tsx`
  — Q vs Q* explainer, newsvendor calculator.
- `apps/web/app/dashboard/[id]/stress/page.tsx` + `StressTestClient.tsx` —
  every variable has a `HelpTooltip`.
- `apps/web/app/dashboard/[id]/reorder/page.tsx` + `ReorderPageClient.tsx`
  — read-only ranked queue (draft-PO feature was removed 2026-05-05).
- `apps/web/app/dashboard/[id]/quality/page.tsx` + `DataQualityReport.tsx` —
  composite score with profile chip + change link.
- `apps/web/app/dashboard/[id]/settings/page.tsx` — Reference profile dropdown
  triggers server-side rescore via `PATCH /metadata`.
- `apps/web/components/InsightsPanel.tsx` + `LlmInsightsPanel.tsx` +
  `SkuNarrativeCard.tsx` — heuristic-first insights with optional LLM
  enrichment.
- `apps/web/lib/insights.ts` — `deriveForecastInsights`,
  `deriveSupplierInsights`, `deriveSkuHeuristics`, `summarize*` for LLM
  context.
- `apps/web/lib/theme.tsx` + `components/ThemeToggle.tsx` — dark mode.
- `apps/web/lib/api-client.ts` — fetch helpers for every backend route.
- `apps/web/lib/types.ts` — TypeScript mirror of every Pydantic schema.
  `DatasetPreview.detected_connector` field tags Shopify-format uploads.
- `apps/web/components/ChatPanel.tsx` — SSE chat with agent lane (handles
  `router_decision` / `agent_start` / `agent_dispatch` / `agent_complete`
  / `cost_cap_hit` SSE events). Single-agent and multi-agent paths render
  uniformly.
- `apps/web/app/upload/templates/page.tsx` — ERP column-shape reference
  for Shopify / NetSuite / SAP / QuickBooks / Square.
- `apps/web/playwright.config.ts` + `apps/web/tests/e2e/*.spec.ts` —
  smoke tests. Run locally: `cd apps/web && npm install &&
  npx playwright install chromium && npm run test:e2e`.
- `.github/workflows/ci.yml` — backend pytest, frontend typecheck/lint,
  Playwright smoke, gated agent-eval (requires repo
  `ANTHROPIC_API_KEY` secret).

---

## Reference: the big plan

A detailed plan that drove the 2026-05-05 forecasts UX overhaul + profile-based
data-quality scoring is at:

`/Users/shantkoutnouyan/.claude/plans/so-now-i-need-jazzy-sunrise.md`

If a future request feels like it's revisiting that scope, read that plan
first to see what's already done and what was deferred.

---

## What's deferred / out-of-scope

- **`closed` triple-state on the `Yesterday` column** — backend doesn't
  currently distinguish 0 (no demand) vs `—` (no data) vs closed (store
  closed). The third state needs a new ingestion field; out of scope for now.
- **Email-to-buyer / "approve & send to ERP"** — would need supplier-contact
  integration + outbound mail. Out of scope.
- **Migration tooling** — DuckDB schemas are inline (`apps/api/db.py`); no
  Alembic. Profile metadata is sidecar JSON; no migration framework needed.
- **Draft PO / AutoPlan** — removed 2026-05-05 at user request. The reorder
  queue is read-only triage now. The backend `/reorder/draft` and
  `/purchase_orders` endpoints still exist but no UI calls them. If
  resurrecting the feature, the prior `AutoPlanModal.tsx` was deleted; check
  git history if a reference is needed.

### Research-track items (deferred unless GPU/training time is approved)

All section-1.x items from the Wilkinson plan except 1.5 are deferred. The
app/agent feature set is complete; these would extend the research story.
Pickable in any order — most are CPU-only.

- **1.7 Chronos LoRA fine-tune** *(GPU required)* — A10 GPU on Modal, ~2h,
  $2-5. Train a parameter-efficient LoRA adapter on M5 retail. Highest
  research-track leverage; produces `chronos_lora_retail.pt` (<10 MB) that
  ships with M5 artifacts and wires into `forecasting/foundation.py`.
- **1.2 Stacking meta-learner** *(CPU)* — LightGBM on out-of-fold pinball
  losses → per-(SKU, horizon) ensemble weights. Trains on existing
  backtest output; no new data needed.
- **1.6 Hierarchical Bayesian with NUTS** *(CPU)* — NumPyro on CPU.
  Replaces the closed-form Poisson/Gamma cold-start with proper
  SKU-Category-Department partial pooling.
- **1.8 MDN demand head** *(CPU)* — small MLP outputting a 3-component
  NegBin mixture from ensemble + interval + SKU features.
- **1.9 Bayesian lead-time per (supplier, SKU)** *(CPU)* — hierarchical
  Gamma priors; updated from receipt history.
- **1.11 N-BEATS-Interpretable** *(GPU helpful, CPU OK)* — deep learning
  decomposition replacing STL.
- **1.12 Probabilistic hierarchical reconciliation** *(CPU)* — upgrade
  from MinT-shrink (point) to probabilistic via `hierarchicalforecast`.

### LLM-track items already shipped

- 3.1 LLM-as-forecaster (LLMTime) — `apps/api/forecasting/llm_forecaster.py`,
  feature-flagged via `ENABLE_LLM_FORECASTER=1`.
- 3.2 LLM-extracted SKU features — `apps/api/llm/sku_features.py`, joined
  into LightGBM via `apps/api/forecasting/ml.py`.
- 3.4 LLM-grounded anomaly explanation — `apps/api/llm/anomaly_explainer.py`,
  returns structured `judgment` alongside narrative `explanation`.
- 3.5/4.3 Multi-agent system — see "Multi-agent chat" architecture note above.
- 3.6 LLM-as-judge — `apps/api/llm/judge.py`, used by `agent_eval.py`.
- 3.7 NL-to-query — `apps/api/llm/nl_query.py`.
- 3.8 LLM-narrated dashboard tour — `apps/api/llm/tour.py`.
- 4.1 plan_reorder_week — `apps/api/inventory/recommend.py` +
  `inventory/routes.py` REST endpoint.
- 4.4 Scheduled briefing — `apps/api/llm/briefing.py` + Modal cron in
  `modal_app.py`.
- 5.2 Agent task suite — `evals/agent_tasks.yaml` + `agent_eval.py`.
- 6.1 Sentry — code path live; needs `SENTRY_DSN` in Modal secret.
- 6.3 Playwright + CI — `apps/web/tests/e2e/`, `.github/workflows/ci.yml`.
- 6.5 Latency instrumentation — `observability.py` middleware.
- 7.1 Shopify connector — `apps/api/ingestion/connectors/shopify.py`.
- 7.3 ERP templates — `apps/web/app/upload/templates/page.tsx`.

### LLM-track items not shipped

- **3.3 LLM schema mapping** — would replace/augment `ingestion/mappers.py`.
  Existing ML mapper is at ~85% accuracy on demo data; not high-leverage.
- **3.10 Extended thinking** — `enable_thinking=True` parameter exists on
  `run_chat_blocking` but defaults off. Sonnet 4.6 without thinking is fine
  for current loads.
- **3.11 LLM-generated test cases** — fun but lower-leverage than the
  Playwright + agent-eval coverage that already shipped.
- **3.12 RAG over inventory literature** — needs a corpus + retrieval infra.
