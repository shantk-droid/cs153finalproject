# Demo script — Universal SKU Optimizer

**Target:** 4-minute Loom + live class walkthrough.
**Stack on demo day:** live Vercel URL → Vercel `/api/*` proxy → Modal API. Local docker-compose (`infra/docker-compose.yml`) is the fallback if Modal is cold/flaky.

## Pre-demo checklist (run an hour before)
1. `curl https://shantk--inventory-optimizer-fastapi-app.modal.run/health` — confirm 200 + `m5_calibration_version` populated.
2. Open the live Vercel URL once to warm Modal's container (skip cold-start hit during demo).
3. Have **three pre-generated sample CSVs** ready in your file picker:
   - `data/samples/retail_stable.csv` — 200 SKUs, weekly, smooth (fast happy-path)
   - `data/samples/coffee_perishable.csv` — 80 SKUs, daily, perishable (newsvendor)
   - `data/samples/ecommerce_lumpy.csv` — 300 SKUs, weekly, intermittent (lumpy stress)
4. Have one of the M5 raw CSVs (`data/raw/sales_train_evaluation.csv`) ready as the "real-world data" demo if asked.
5. Open browser tabs:
   - Tab 1: live Vercel URL `/upload`
   - Tab 2: live Modal `/health` (proves backend is up)
   - Tab 3: Modal dashboard (in case you need to show the deploy)

## 4-minute walkthrough (Loom + live class)

**0:00 — 0:15 · Hook**
> "Small retailers and DTC brands run inventory in spreadsheets. Enterprise tools cost six figures. This is a self-serve, AI-native middle ground — drop your data in, get back forecasts and reorder recommendations in minutes."

Action: show the landing page, click "Try it now."

**0:15 — 0:45 · Upload & DQ**
> "Drop in any CSV or Excel. The system auto-detects columns, runs schema validation, and grades the data on five dimensions before it'll even forecast."

Action: drop `retail_stable.csv`. Confirm the column mapping (everything auto-detected). Land on the DQ report — point out:
- Composite score (number on the left)
- 5 sub-scores: completeness / plausibility / **statistical fit (vs M5)** / history depth / **stationarity / regime stability**
- Click into one assertion to show the offending rows
- Mention: "If we have an Anthropic key, the LLM rewrites these warnings in plain English. That's the `?explain=true` query param."

**0:45 — 1:30 · Dashboard**
> "Continue to the dashboard. Every SKU classified ABC × XYZ; the table is virtualized so 50K SKUs scroll smoothly. There's a joint-replenishment recommender that pools SKUs by supplier — saves real fixed-order cost."

Action: scroll the SKU table, click ABC=A filter, hover the ABC×XYZ heatmap cells (each cell tells you the recommended policy). Point at the joint-replen panel: "$128k/yr saved on the synthetic data."

**1:30 — 2:30 · SKU detail**
> "Click any SKU. This is where the depth lives."

Action: click the top revenue SKU. Point at:
- Forecast chart with 80/95% bands; the bands are **conformal-calibrated** — empirical coverage on backtest residuals is reported in caveats
- Recommendation card: policy + safety stock + stockout probability + fill rate
- **Order schedule** below the chart: 12 weeks of planned orders, with delivery dates
- Scenario sliders on the right: "If lead times double, watch safety stock jump in real time" — drag the slider to 2.0×
- Calibration card: "How does this SKU's CV compare to M5 retail norms? It's at the 73rd percentile."

**2:30 — 3:30 · Chat**
> "All of this is also an inventory analyst chat. Sonnet 4.6 with tool use — it calls the same APIs you just clicked."

Ask, in order:
1. "How many SKUs do I have and what's my total annual revenue?" → tool: `get_aggregate_stats`
2. "If lead times double for SKU-00061, how much extra safety stock?" → tool: `run_scenario`, shows base vs scenario delta inline
3. "Is SKU-00061's demand variability normal for retail?" → tool: `compare_to_m5`, reports percentile vs M5

Highlight: extended thinking budget is on (1024 tokens), prompt caching is wired (system prompt + tools + dataset summary cached), eval harness blocks merges below 90% pass rate.

**3:30 — 3:50 · Export + close**
> "Export the recommendations as XLSX, send to your supplier. Three things made this possible without an enterprise budget: M5 Walmart calibration baked into the engine, a five-component data-quality contract, and a chat layer with a real eval harness — not a vibe demo."

Action: click "Export XLSX" in the dashboard header. File downloads.

**3:50 — 4:00 · Tech & link**
> "Live URL is in the description. Built with Next.js + FastAPI on Vercel + Modal. 168 tests, full CI. Source on GitHub."

## What to say if asked

- **"How is the M5 data used?"** → priors for Bayesian shrinkage on cold-start SKUs (NegBin posterior), pattern classifier (LightGBM, val acc 99.5%), calendar/holiday/SNAP features, reference distributions for the DQ statistical-fit score.
- **"Why three forecast methods?"** → Different SKUs need different models. Smooth → ETS. Seasonal → ARIMA. Intermittent → Croston. Cold-start → Bayesian shrinkage. We ensemble {classical, Chronos-Bolt, LightGBM} weighted by inverse backtest CRPS, then conformal-calibrate the intervals.
- **"Why conformal calibration?"** → Base-model intervals can have wrong coverage. Conformal *guarantees* nominal coverage on the empirical distribution of residuals. Day 8 e2e: 92% empirical coverage on the nominal 95% interval.
- **"What about stockouts?"** → The 5-policy inventory math integrates over the full predictive distribution (not normal approximation). (s,S) is solved by Monte-Carlo simulation. The recommendation includes expected stockout probability and fill rate, both computed from the actual distribution.
- **"What's not built?"** → Multi-echelon optimization, real-time integrations (Shopify/Amazon), full multi-tenancy. v1 is single-dataset, password-gated. The architecture is ready to extend.

## Demo failure mitigations

- **Modal cold start on demo day** — open the live URL ~10 min before. Cold start is the only ~5s pause; warm requests are <1s for chat tools.
- **Anthropic budget hit** — eval harness rate-limited; live demo is 3 questions × ~$0.015 = $0.05. Spending alert at $200 on the console.
- **Vercel build failure** — fall back to local docker-compose. `cd infra && docker compose up`.
- **Forecasts look weird on user's data** — caveats surface low-history (<8 obs refusal), regime breaks, and intermittent/lumpy patterns. Pre-test on a real Excel file from a friend before demo day.
