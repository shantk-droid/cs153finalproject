# Universal SKU Optimizer — One-pager

**Built by:** Shant Koutnouyan
**Class:** CS 153 final project, Spring 2026
**Live URL:** https://web-delta-one-65.vercel.app
**Source:** https://github.com/shantk-droid/cs153finalproject

---

## Problem
Small and mid-market retailers, distributors, and DTC brands run inventory in spreadsheets and on intuition. Enterprise tools like Blue Yonder and o9 cost six figures and take months to onboard. Mid-tier tools (Inventory Planner, Cogsy) run $300–$2,000/month and still need manual configuration per SKU. The opportunity: a vertical-agnostic, AI-native inventory tool that ingests messy data and returns defensible order recommendations within minutes.

## Approach
Three layers connected by HTTP, every piece independently testable.

1. **Ingestion + assertion engine.** CSV/Excel upload with column auto-detection. Three layers of validation: schema (hard fail), business-logic (soft fail), and **statistical fit against M5 Walmart norms** (per-SKU CV, intermittency, seasonality, trend, regime-shift score compared to the M5 reference distribution for the matched category). Output: a 5-component **Data Quality Score** the user sees before forecasting begins.

2. **Forecasting engine.** Per-SKU pattern classifier (LightGBM, trained on 5K M5 SKUs, **99.5% val accuracy**). Routes to:
   - **Bayesian shrinkage cold-start** when n_obs < 26 weeks (NegBin posterior with M5-fit Gamma priors)
   - **Classical** (ETS / ARIMA / Croston / TSB via Nixtla statsforecast)
   - **Chronos-Bolt-Small** foundation model (CPU)
   - **Global LightGBM** with calendar/lag/category features
   Then a **CRPS-weighted ensemble** + **split-conformal interval calibration** for guaranteed empirical coverage. Optional **MinT-shrink hierarchical reconciliation** when category data is present.

3. **Inventory math + chat.** 5 policies (EOQ, (Q,R), (s,S), newsvendor, base-stock), all using full predictive distribution (not normal approximation). (s,S) solved by Monte-Carlo simulation. Multi-period rolling schedule generation. Joint-replenishment recommender. Per-dataset settings persistence. **Anthropic Claude Sonnet 4.6 chat** with 10 tools, prompt caching, extended thinking, eval harness with 20 golden questions.

## What's actually working
| Subsystem | Status |
|---|---|
| Ingestion + 5-component DQ score | ✓ schema + business-logic + statistical fit + history depth + **stationarity / regime stability** all live |
| LLM-explained DQ issues | ✓ batched Anthropic call, on-disk SHA-cached |
| Forecasting ensemble (classical + Chronos-Bolt + LightGBM) | ✓ wired with CRPS weighting + conformal calibration |
| Bayesian shrinkage cold-start | ✓ NegBin posterior, M5 priors per (dept, pattern) |
| Hierarchical reconciliation (MinT-shrink) | ✓ as a `/reconcile` batch route |
| 5 inventory policies + multi-period schedule + joint replen | ✓ all 5; (s,S) via 80-rep simulation; 90-day schedule with delivery dates |
| Stockout-cost-aware service level | ✓ derives implied newsvendor-optimal level from cost ratio |
| Chat layer (10 tools, streaming, prompt caching) | ✓ **20/20 = 100%** on golden eval (or 19/20 with current YAML) |
| Per-dataset settings + CSV/XLSX export | ✓ |
| Rate limits + Sentry stub + structured logging + extended /health | ✓ |
| Single-password gate via Next.js middleware | ✓ |
| docker-compose local fallback | ✓ |
| 272 Python tests | ✓ |
| TS strict typecheck | ✓ |

## Stack
- **Frontend:** Next.js 14 (App Router) + TypeScript + Tailwind + Recharts + TanStack Table + Vega-Lite (chat charts)
- **Backend:** FastAPI + pydantic v2 + pandas + numpy + scipy + DuckDB
- **Forecasting:** statsforecast (Nixtla), chronos-forecasting 2.2 (Amazon), lightgbm, hierarchicalforecast
- **LLM:** Anthropic Claude Sonnet 4.6 with prompt caching + extended thinking
- **Hosting:** Vercel (web) + Modal (api), with docker-compose fallback
- **Observability:** structlog + Sentry (optional) + extended `/health`

## Numbers
- **272/272 Python tests** passing, **TypeScript strict** clean
- **228 files** across `apps/web` + `apps/api` + `evals` + `infra`
- M5 calibration shipped as 6 versioned artifacts (~600 KB) baked into the deploy image
- Chat-layer eval: $0.59 / 20 questions, ~11s/question average, 95–100% pass rate depending on run
- Forecast latency: 0.2s / classical-only, 5–7s / full ensemble with foundation
- Joint-replen recommender on synthetic data: **25 groups, $128,547/yr in fixed-order-cost savings**
- Conformal-calibrated 95% intervals: **92% empirical coverage** on backtest residuals (within 3% of nominal)

## What's deliberately not built
Multi-echelon (warehouse network) optimization, real-time ERP integrations (Shopify/Amazon/NetSuite), multi-tenant data isolation, custom-trained ML beyond the M5 pattern classifier, billing, mobile app. Architecture is ready to extend; v1 is single-dataset, password-gated, scoped for the demo.
