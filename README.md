# Inventory Optimizer

CSV/Excel → demand forecasts + reorder recommendations + multi-agent Claude
chat. Calibrated against the M5 Walmart dataset.

**Live:**
- Web — https://web-delta-one-65.vercel.app
- API health — https://shantk--inventory-optimizer-fastapi-app.modal.run/health

Built for **CS 153 (Spring 2026)** as the final project. The class-submission
one-pager lives at [docs/ONE_PAGER.md](docs/ONE_PAGER.md); a 4-minute Loom
walkthrough script is at [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). Working
context for editing the codebase is in [CLAUDE.md](CLAUDE.md).

---

## Why this exists

Small and mid-market retailers, distributors, and DTC brands run inventory in
spreadsheets and on intuition. Enterprise tools (Blue Yonder, o9) cost six
figures and take months to onboard. Mid-tier tools (Inventory Planner, Cogsy)
run $300–$2,000/month and still need manual configuration per SKU.

The opportunity: a **vertical-agnostic, AI-native inventory tool** that ingests
messy data and returns defensible order recommendations within minutes.

What's different about this build:

- **Profile-aware data quality** — a 5-component DQ score is computed against
  one of 5 industry reference profiles, not a single hardcoded baseline.
- **Full predictive distribution** — every inventory policy uses the actual
  forecast distribution (not a normal approximation around a point forecast).
- **Methodology drawer on every metric** — formula + inputs + assumptions +
  current values, one click away. Most enterprise tools are black boxes.
- **Multi-agent chat** — Router → Planner → Forecaster/Risk/Buyer
  specialists, with a per-call USD ceiling and a daily cost ledger.
- **Grounded, not generated** — anomaly detection runs deterministically
  server-side; the LLM only writes the prose. The auto-plan agent's output
  is forced through a typed tool and re-validated against the panel.
  The LLM is never trusted with prices.

---

## What you can do with it

The dashboard has **9 surfaces** under `/dashboard/[id]`, each backed by typed
FastAPI endpoints (~50 routes total).

### Ingestion
- CSV / XLSX upload with column auto-detection
  ([apps/api/ingestion/routes.py](apps/api/ingestion/routes.py)).
- **Shopify CSV connector** with auto-detection of line-item exports
  ([apps/api/ingestion/connectors/shopify.py](apps/api/ingestion/connectors/shopify.py)).
- **6 demo templates** bootstrap a complete dataset (panel + suppliers +
  receipts) without an upload — `retail_stable`, `coffee_perishable`,
  `ecommerce_lumpy`, `b2b_industrial`, `pharma_steady`, `spare_parts_mro`.
  Each is calibrated to a profile centroid.
  `POST /datasets/demo/{template}` creates one in seconds.
- **ERP template reference** at [/upload/templates](apps/web/app/upload/templates/page.tsx)
  — column shapes for Shopify / NetSuite / SAP / QuickBooks / Square.

### Data quality
- 5-component composite (completeness, plausibility, statistical fit vs
  profile, history depth, stationarity) — see
  [apps/api/assertions/score.py](apps/api/assertions/score.py).
- **Profile picker** — 5 industries, swap from the Settings page and the
  report rescore lazily on next read. Profiles live as JSON at
  [apps/api/profiles/data/](apps/api/profiles/data/).
- Soft-penalty scoring against per-profile p2 / p10 / p90 / p98 quantiles.
  No hard pass/fail.

### Forecasting
- **Ensemble** of classical (statsforecast: AutoETS / AutoARIMA / Croston /
  TSB / SeasonalNaive), Chronos-Bolt-Small foundation model, global LightGBM
  with calendar + lag features, and Bayesian shrinkage cold-start (NegBin
  posterior with M5 Gamma priors when `n_obs < 26 weeks`).
- **CRPS-weighted ensemble combiner**, then **per-horizon split conformal**
  calibration so the 95% interval has honest empirical coverage.
- **LLMTime forecaster** as an optional ensemble member — Sonnet-as-forecaster
  via forced-tool output, off by default
  ([apps/api/forecasting/llm_forecaster.py](apps/api/forecasting/llm_forecaster.py)).
- **STL-style decomposition** (trend / seasonal / residual) and **per-method
  leaderboard** on the SKU detail page.
- **Hierarchical reconciliation** (MinT-shrink) when category data is present.

### Inventory math
- 5 policies — EOQ, (Q,R), **(s,S)** (default, solved by Monte Carlo
  simulation), newsvendor (perishable categories auto-route here),
  base-stock.
- ABC × XYZ classification.
- **Multi-period rolling schedule** with delivery dates over a 90-day
  horizon.
- **Joint-replenishment recommender** that groups SKUs sharing a supplier.
- Stockout-cost-aware service level — derives implied newsvendor-optimal
  level from the cost ratio.

### Reorder & POs
- Ranked queue scored by `stockout_prob × revenue_at_risk`, MOQ +
  case-pack rounded to executable quantities.
- **PO state machine** — `drafted → approved → placed → received` (linear)
  + `cancelled` from any non-terminal state, with audit log per transition.
- Multi-line POs supported.
- **CSV + EDI 850 export** — minimal valid X12 envelope, no extra deps.

### Suppliers
- Scorecards: OTIF / on-time / in-full / lead-time mean+std / MOQ /
  payment terms.
- Detail page shows **Bayesian posterior lead time** — gamma + normal-approx
  conjugate update from receipt history.

### Risk + working capital
- **Stress test** — sliders for lead-time × demand × service-level shocks
  → VaR/CVaR 95% + top-10 impacted SKUs.
- **Cash-to-cash** = DIO + DSO − DPO; DSO assumed 0 (no AR data) and
  documented as such.

### Multi-agent chat
- Default route at `POST /datasets/{id}/chat` (SSE).
- A **Haiku Router** classifies each turn into `single` (existing
  single-agent loop with 11 tools) or `multi` (Planner decomposes via
  `dispatch_specialist` into Forecaster / Risk / Buyer specialists).
  Pass `?single=1` to bypass.
- SSE event stream surfaces `router_decision`, `agent_start`,
  `agent_dispatch`, `agent_complete`, `cost_cap_hit` to the
  [Agents lane](apps/web/components/ChatPanel.tsx) in the UI.
- **Per-call ceiling**: `$0.50` (`MULTI_AGENT_USD_CEILING` in
  [orchestrator.py](apps/api/llm/orchestrator.py)). **Daily ceiling**:
  enforced by [cost_ledger.py](apps/api/llm/cost_ledger.py); chat returns
  HTTP 429 when exceeded.
- **NL-to-SQL** with regex allowlist (banned: `DROP`, `INSERT`, `ATTACH`,
  `COPY`, `PRAGMA`, CTEs, multi-statement) + table allowlist + DuckDB
  opened read-only. 16 adversarial tests pin the behavior.

### Agentic features
- **Anomaly explainer** — deterministic CUSUM + robust z-score detector
  ([anomaly.py](apps/api/llm/anomaly.py)); LLM only writes the narrative
  AND a structured `judgment` (`{cause, confidence, evidence,
  suggested_adjustment, source}`) via the
  `submit_anomaly_explanation` forced tool.
- **Auto-plan agent** — pre-computes the reorder queue, forces a typed
  `submit_plan` tool call, then re-validates every line against the
  panel (sku_id existence, MOQ + case-pack rounding, unit_cost
  re-fetched).
- **Scheduled morning briefing** — Modal cron at 14:00 UTC fires
  [briefing.py](apps/api/llm/briefing.py) per dataset; cached daily.
- **LLM-narrated dashboard tour** — 4-step welcome tour, cached 30 days,
  with canned heuristic fallback.

Every agentic endpoint has a deterministic fallback path — the UI never
blocks on Anthropic availability.

### Trust layer
- `MethodologyDrawer` next to every KPI: formula, inputs, assumptions,
  current values.
- `HelpTooltip` on every abbreviated column header (OTIF, DIO, CRPS, MASE,
  …) — pure CSS, no Radix dep.

---

## Architecture

Two services that **must be deployed separately**. The web proxies all
`/api/*` requests through `MODAL_API_URL` to the Python backend.

```
                ┌─────────────────────┐
   browser ───▶ │ Vercel (Next.js 14) │
                │  app/api/[...path]  │ ──▶ MODAL_API_URL
                └─────────────────────┘            │
                                                   ▼
                                       ┌────────────────────────┐
                                       │ Modal (FastAPI)        │
                                       │ apps/api/modal_app.py  │
                                       │  • DuckDB per dataset  │
                                       │  • M5 artifacts in img │
                                       │  • Volume /root/data   │
                                       └────────────────────────┘
                                                   │
                                                   ▼
                                       Anthropic API (Sonnet 4.6 + Haiku)
```

### Headline request flow — multi-agent chat

```
browser
  └─▶ POST /api/datasets/{id}/chat        (Vercel proxy)
        └─▶ POST /datasets/{id}/chat       (Modal)
              └─▶ orchestrator.py
                    ├─▶ Router (Haiku)             → "single" | "multi"
                    └─▶ Planner (Sonnet) ──tool──▶ dispatch_specialist
                          └─▶ Forecaster | Risk | Buyer
                                └─▶ run_chat_blocking(tool_subset=…)
                                      └─▶ executors.py (DuckDB / forecast / recommend)
        ◀─SSE event stream─┘
        (router_decision / agent_dispatch / agent_complete / cost_cap_hit)
```

### Data plane

- **Per-dataset DuckDB** file at `{data_dir}/datasets/{dataset_id}.duckdb`
  ([apps/api/db.py](apps/api/db.py)). No shared schema, no migrations.
- **Sidecar JSON** at `{data_dir}/metadata/{dataset_id}.json` carries
  per-dataset settings (selected profile, service level, holding cost,
  order cost, review period). On read miss, falls back to
  `profile_id = "retail_m5"`.
- **M5 calibration artifacts** baked into the Modal image at
  [apps/api/m5/artifacts/](apps/api/m5/artifacts/) — `series_priors.parquet`,
  `pattern_classifier.lgb`, `calendar_effects.json`, `category_defaults.json`,
  `dq_reference_dists.parquet`. Read-only at runtime.
- **LLM caches** (insights, briefings, tour, anomaly explanations,
  SKU-feature labels) live under `{data_dir}/llm_insights/`, sha256-keyed.
  Repeat dashboard visits cost $0.

### Cost controls

- Per-call USD ceiling on the multi-agent loop (`$0.50`).
- Daily ledger (`apps/api/llm/cost_ledger.py`) → HTTP 429 when exceeded.
- 30 req/min/IP rate limit on `/chat`; 20/hour/IP on uploads.
- Heuristic fallback path on every agentic endpoint.

### A non-obvious detail worth knowing

Dispatcher state in the multi-agent loop is stored in `threading.local()`
([executors.py](apps/api/llm/executors.py) `_set_active_dispatcher`),
**not** a module global. Under concurrent /chat requests, a global would
let Planner A end up using Planner B's dispatcher and read B's dataset
(cross-tenant leak). Keep this thread-local.

---

## Tech stack

### Frontend
| | |
|---|---|
| Framework | Next.js 14.2 (App Router, server components by default) |
| Language | TypeScript 5 (strict) |
| Styling | Tailwind CSS 3.4 + shadcn/ui + Radix primitives |
| Charts | Recharts 2.13 (SKU pages) + Vega-Lite 5 (chat) |
| Tables | TanStack Table 8 + React Virtual 3 |
| Data fetching | TanStack React Query 5 |
| Markdown | react-markdown + remark-gfm |
| Toast | sonner |
| Validation | Zod 3 |
| Theme | Custom dark-mode tokens in [globals.css](apps/web/app/globals.css) |

### Backend
| | |
|---|---|
| Framework | FastAPI 0.115 + uvicorn + pydantic v2 |
| Data | pandas + numpy + scipy + DuckDB 1.0 + PyArrow + openpyxl |
| Forecasting | statsforecast (Nixtla), chronos-forecasting (Bolt, CPU), lightgbm, hierarchicalforecast, numpyro (cold-start) |
| LLM | anthropic ≥0.34 — Sonnet 4.6 + Haiku, prompt caching, extended thinking, tool use |
| Observability | structlog + sentry-sdk[fastapi] (dormant until DSN set) |
| Storage | per-dataset DuckDB file; raw uploads on disk; sidecar JSON for metadata |

### Hosting
| | |
|---|---|
| Web | Vercel (`shantk-5857s-projects/web`) |
| API | Modal (`inventory-optimizer`) — A10/CPU with persistent volume `inventory-optimizer-data` |
| Secrets | Modal: `inventory-secrets` (`ANTHROPIC_API_KEY`, optional `SENTRY_DSN`); Vercel: `MODAL_API_URL`, `ANTHROPIC_API_KEY` |
| CI | GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) |

---

## Project layout

```
.
├── apps/
│   ├── api/                       # FastAPI on Modal
│   │   ├── main.py                # router registration
│   │   ├── modal_app.py           # Modal deploy config + cron
│   │   ├── config.py              # pydantic-settings (override=True for ANTHROPIC_API_KEY)
│   │   ├── db.py                  # per-dataset DuckDB helpers
│   │   ├── synthetic.py           # 6 demo templates calibrated to profile centroids
│   │   ├── observability.py       # Sentry + structlog + latency middleware
│   │   ├── ingestion/             # routes, mappers, validators, demo loader, Shopify
│   │   ├── assertions/            # 3 layers: schema (hard), business-logic (soft), statistical
│   │   ├── profiles/              # registry + 5 industry JSONs in profiles/data/
│   │   ├── forecasting/           # classical + ml (LGB) + foundation (Chronos) + bayes
│   │   │                          # + ensemble + conformal + decompose + leaderboard + llm_forecaster
│   │   ├── inventory/             # 5 policies + multi_period + joint_replen + abc_xyz
│   │   │                          # + reorder_queue + purchase_orders + po_export
│   │   │                          # + supplier_metrics + frontier + stress_test + working_capital
│   │   ├── insights/              # proactive insights compute
│   │   ├── llm/                   # routes, loop, orchestrator, router, specialists,
│   │   │                          # tools, executors, cost_ledger, judge, agent_eval,
│   │   │                          # nl_query, briefing, tour, anomaly, anomaly_explainer,
│   │   │                          # auto_plan, sku_features, insights
│   │   ├── m5/                    # build_calibration.py + read-only artifacts/
│   │   ├── tests/                 # 270+ pytest cases across 26 files
│   │   └── pyproject.toml
│   └── web/                       # Next.js 14 frontend
│       ├── app/
│       │   ├── page.tsx           # landing + LandingActions (demo loader)
│       │   ├── login/             # password gate (single-shared-password middleware)
│       │   ├── upload/            # CSV/XLSX flow + ERP-template reference page
│       │   ├── dashboard/[id]/
│       │   │   ├── layout.tsx     # left-rail nav wrapper
│       │   │   ├── page.tsx       # action queue (no longer a redirect)
│       │   │   ├── overview/      # KPI strip + insights + WC + ABC×XYZ
│       │   │   ├── forecasts/     # sparkline-equipped table, status pills, CSV export
│       │   │   ├── reorder/       # ranked queue (read-only triage)
│       │   │   ├── frontier/      # SL Pareto + newsvendor calculator
│       │   │   ├── suppliers/     # scorecards + [supplierId]/ detail
│       │   │   ├── stress/        # lead-time × demand × SL sliders + VaR
│       │   │   ├── quality/       # DQ composite + profile chip
│       │   │   ├── chat/          # multi-agent SSE chat with Agents lane
│       │   │   └── sku/[skuId]/   # forecast + decomposition + leaderboard + anomaly drawer
│       │   └── api/[...path]/     # proxy to Modal
│       ├── components/            # KpiCards, SkuTable, Sparkline, ForecastChart,
│       │                          # ChatPanel, MethodologyDrawer, HelpTooltip, etc.
│       ├── lib/                   # api-client, types, methodology, theme, insights, sku-status
│       ├── tests/e2e/             # 4 Playwright specs
│       └── playwright.config.ts
├── evals/                         # agent_tasks.yaml (30 tasks) + chat_questions.yaml + forecast_benchmarks.py
├── scripts/                       # dev.sh, seed_demo.sh, build_m5_calibration.sh
├── docs/                          # ONE_PAGER, DEMO_SCRIPT, CLAUDE
├── infra/                         # Dockerfile.api, docker-compose.yml (local fallback)
├── .github/workflows/ci.yml       # backend-tests, frontend-typecheck, playwright-smoke, agent-eval (gated)
├── CLAUDE.md                      # developer / Claude-session context
└── README.md                      # ← you are here
```

---

## Local development

### Prerequisites

| Tool | Version | Why |
|---|---|---|
| Node.js | ≥ 20 | Frontend (Next.js 14) |
| npm | ≥ 10 | workspaces |
| Python | 3.11+ (3.12 tested) | Backend |
| Anthropic API key | optional | enables LLM features; without it, every agentic feature falls back to heuristics |

Kaggle CLI is **not** required for normal development — the M5 calibration
artifacts are committed at [apps/api/m5/artifacts/](apps/api/m5/artifacts/).
You only need Kaggle to rebuild them (`bash scripts/build_m5_calibration.sh`).

### One-shot setup

```bash
# Backend deps in a venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e "apps/api[dev]"

# Frontend deps
npm --prefix apps/web install

# Environment (optional but recommended)
cp .env.example .env
# Set ANTHROPIC_API_KEY=sk-… to enable LLM features.

# Run both servers
bash scripts/dev.sh
```

The dev script starts:
- Web on http://localhost:3000
- API on http://localhost:8000 (`/health`, `/docs`)

The web's API proxy falls back to `http://localhost:8000` when no
`MODAL_API_URL` is set.

### Bootstrap a dataset without uploading

```bash
curl -sS -X POST http://localhost:8000/datasets/demo/coffee_perishable \
  | python3 -m json.tool
# → {"dataset_id": "demo-…", "n_skus": 80, ...}
```

Open `http://localhost:3000/dashboard/<dataset_id>/overview` to see the full
9-section dashboard wired up.

### Tests

```bash
# Backend (270+ tests, ~100s)
.venv/bin/python -m pytest apps/api/tests/

# Frontend typecheck
npm --prefix apps/web run typecheck

# Frontend smoke (Playwright)
cd apps/web && npx playwright install chromium && npm run test:e2e
```

---

## Deployment

Two services, two redeploy commands. **A common failure mode is "I deployed
Vercel and the site is broken" because Modal still has the old API contract.**

### Redeploy matrix

| Touched files | Redeploy |
|---|---|
| `apps/web/**` | Vercel only |
| `apps/api/**` (routes / schemas / scoring) | Modal **and** Vercel if any TS types changed |
| `apps/api/profiles/data/*.json` | Modal only |
| `apps/api/m5/artifacts/*` | Modal only |

### Modal (API)

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/modal \
  deploy apps/api/modal_app.py
```

Production URL: `https://shantk--inventory-optimizer-fastapi-app.modal.run`.
Secret `inventory-secrets` carries `ANTHROPIC_API_KEY`; add `SENTRY_DSN` to
the same secret to light up the dormant Sentry path.

### Vercel (web)

```bash
export PATH="/Users/shantkoutnouyan/.nvm/versions/node/v20.20.2/bin:$PATH"
cd apps/web && npx --yes vercel@latest deploy --prod --yes
```

Production URL: `https://web-delta-one-65.vercel.app`. Required env vars:
`MODAL_API_URL`, `ANTHROPIC_API_KEY` (both encrypted, both
Production+Preview).

### Smoke-test prod end-to-end

After any deploy, all four should return 200 — anything else points at the
layer to fix.

```bash
# 1. Vercel env vars set?
cd apps/web && npx --yes vercel@latest env ls

# 2. Health endpoint reachable end-to-end via the proxy?
curl -sS https://web-delta-one-65.vercel.app/api/health

# 3. Demo POST works end-to-end?
curl -sS -X POST https://web-delta-one-65.vercel.app/api/datasets/demo/coffee_perishable

# 4. SSR dashboard page renders for the new dataset?
DSID=$(curl -sS -X POST https://web-delta-one-65.vercel.app/api/datasets/demo/coffee_perishable \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['dataset_id'])")
curl -sS -o /dev/null -w "%{http_code}\n" \
  "https://web-delta-one-65.vercel.app/dashboard/${DSID}"
```

---

## Testing & CI

### Local test suites
- **Backend**: `pytest` over [apps/api/tests/](apps/api/tests/) — 270+
  cases across 26 files, ~100 s. Per-test `tmp_path` data dirs;
  [conftest.py](apps/api/tests/conftest.py) sets `OMP_NUM_THREADS=1`
  to avoid lightgbm + libomp segfaults under threaded TestClient on
  macOS arm64, and `RATELIMIT_DISABLED=1` so slowapi doesn't bleed
  across tests.
- **Frontend typecheck**: `npm --prefix apps/web run typecheck`
  (TypeScript strict, clean).
- **Frontend e2e smoke**: 4 Playwright specs in
  [apps/web/tests/e2e/](apps/web/tests/e2e/) — `landing`,
  `dashboard-shell`, `upload`, `templates`. Chromium only.

### CI ([.github/workflows/ci.yml](.github/workflows/ci.yml))

| Job | What it does |
|---|---|
| `backend-tests` | Python 3.12, runs the full pytest suite |
| `frontend-typecheck` | Node 20, `tsc --noEmit` + ESLint |
| `playwright-smoke` | Builds Next.js, runs the 4 e2e specs |
| `agent-eval` | **Gated on `ANTHROPIC_API_KEY` repo secret.** Spins up the API server, creates a demo dataset, runs the 30-task multi-agent suite from [evals/agent_tasks.yaml](evals/agent_tasks.yaml) with LLM-as-judge ([apps/api/llm/judge.py](apps/api/llm/judge.py)). |

The chat eval lives separately at
[evals/chat_questions.yaml](evals/chat_questions.yaml); the M5 forecast
benchmark stub at [evals/forecast_benchmarks.py](evals/forecast_benchmarks.py).

---

## What's deliberately not built

These are explicit non-goals; the architecture extends to support them but
v1 is single-dataset, password-gated, scoped for the demo.

- **Real auth** — single shared-password middleware is sufficient.
- **Multi-tenant data isolation** — out of scope.
- **Multi-echelon (warehouse network) optimization** — single-node only.
- **Real-time integrations beyond Shopify CSV** — no Amazon / NetSuite /
  SAP / QuickBooks live connectors.
- **Custom-trained ML beyond the M5 pattern classifier** — research-track
  items (Chronos LoRA fine-tune, hierarchical Bayesian NUTS, MDN demand
  head, N-BEATS-Interpretable) are documented in [CLAUDE.md](CLAUDE.md)
  but unshipped.
- **Billing / subscription / mobile app** — out of scope.
- **Email-to-buyer / "approve & send to ERP"** — would need supplier-contact
  integration + outbound mail.
- **Comments / collaboration / Slack-Teams digests / outbound webhooks**
  — out of scope.

---

## AI usage disclosure

Per the CS 153 AI policy, here is how and where AI tools were used.

- **Built with Claude Code (Anthropic).** The codebase was developed across a
  14-day MVP and a subsequent MVP+ expansion using Claude Code as a
  pair-programming agent — scaffolding, implementation, tests, refactors, and
  deployment were done in collaboration with Claude (Sonnet). The day-by-day
  build log, design decisions, and working context are preserved in
  [CLAUDE.md](CLAUDE.md) and its linked plan files; the commit history on
  `main` is the development artifact. No external application or starter
  template was forked — the application code is original to this project.
- **Claude in the running product.** Several runtime features call the
  Anthropic API (Claude Sonnet 4.6 + Haiku): the multi-agent chat (Router /
  Planner / Forecaster–Risk–Buyer specialists), the anomaly explainer, the
  auto-plan agent, the scheduled briefing, the dashboard tour, NL-to-SQL,
  LLM-extracted SKU features, and the optional LLMTime forecaster. Every one
  of these has a deterministic fallback, so the product runs with the key
  unset.
- **Design boundary — grounded, not generated.** The LLM is never trusted with
  numbers that matter. Anomalies are detected deterministically server-side and
  the model only writes the prose; the auto-plan agent's output is forced
  through a typed tool and re-validated line-by-line against the panel (sku_id
  existence, MOQ + case-pack rounding, unit_cost re-fetched). The LLM never
  sets prices or quantities.

## Citations & acknowledgements

- **M5 Forecasting / Walmart dataset** — Makridakis, Spiliotis &
  Assimakopoulos, the M5 Competition (Kaggle, 2020). Used to fit the cold-start
  priors, pattern classifier, calendar effects, category defaults, and
  data-quality reference distributions baked into
  [apps/api/m5/artifacts/](apps/api/m5/artifacts/).
- **Nixtla `statsforecast`** — AutoETS / AutoARIMA / Croston / TSB /
  SeasonalNaive classical baselines.
- **Amazon `chronos-forecasting` (Chronos-Bolt)** — pretrained time-series
  foundation model, run on CPU as an ensemble member.
- **`lightgbm`** — global gradient-boosted forecaster + the M5 pattern
  classifier.
- **Nixtla `hierarchicalforecast`** — MinT-shrink reconciliation
  (Wickramasuriya, Athanasopoulos & Hyndman, 2019).
- **Split conformal prediction** — Vovk et al.; Angelopoulos & Bates (2021) —
  for honest empirical interval coverage.
- **LLMTime** — Gruver, Finzi, Qiu & Wilson, "Large Language Models Are
  Zero-Shot Time Series Forecasters" (NeurIPS 2023) — basis for the optional
  LLM-as-forecaster ensemble member.
- **`numpyro`** — Bayesian shrinkage cold-start.
- **Frontend** — Next.js, shadcn/ui + Radix primitives, Recharts, Vega-Lite,
  TanStack Table/Query.
- **Anthropic Claude** (Sonnet 4.6 + Haiku) — all LLM features above.

Third-party libraries are used via their public package APIs and pinned in
[apps/api/pyproject.toml](apps/api/pyproject.toml) and
[apps/web/package.json](apps/web/package.json).

## Further reading

- [docs/ONE_PAGER.md](docs/ONE_PAGER.md) — class-submission summary, problem
  statement, status matrix, headline numbers.
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) — minute-by-minute Loom
  walkthrough script with action cues and pre-demo checklist.
- [CLAUDE.md](CLAUDE.md) — full developer context: architecture deep-dives,
  deployment scars, testing gotchas, working preferences, and the
  outstanding-work snapshot.
