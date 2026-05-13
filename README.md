# Inventory Optimizer

CSV/Excel → demand forecasts + reorder recommendations + Claude tool-use chat. Calibrated against the M5 Walmart dataset.

The full architecture plan lives at `~/.claude/plans/look-at-the-build-quiet-meteor.md`. The original PDF brief is `sku_optimizer_build_plan.pdf`.

## What's in this repo today (Day 1)

- Monorepo skeleton: `apps/web` (Next.js 14), `apps/api` (FastAPI), `data`, `evals`, `scripts`, `docs`, `infra`.
- `docs/CLAUDE.md` — persistent context loaded by every Claude Code session.
- FastAPI shell with `/health` reporting M5 calibration version.
- Next.js shell with `/`, `/upload`, `/dashboard` placeholder pages.
- Synthetic data generator (`apps/api/synthetic.py`) with three vertical templates and unit tests.
- M5 calibration first cut (`apps/api/m5/build_calibration.py`) producing `calendar_effects.json` + `category_defaults.json`. `series_priors.parquet`, `pattern_classifier.lgb`, and `dq_reference_dists.parquet` come on Day 7+.
- Dockerfile for the API + docker-compose for local-parity demo fallback.
- Scripts: `dev.sh`, `seed_demo.sh`, `build_m5_calibration.sh`.

## Prerequisites you need to install before the next step

| Tool | Why | Install |
|---|---|---|
| Node.js ≥ 20 | Frontend (Next.js) | `brew install node` or [nvm](https://github.com/nvm-sh/nvm) |
| Python 3.11+ | Backend (you have 3.12) | already installed |
| Kaggle CLI | Download M5 raw data | `pip install kaggle`, then put your token at `~/.kaggle/kaggle.json` (chmod 600). [Generate a token here.](https://www.kaggle.com/settings/account) |
| Git | Version control | already installed |
| (optional) Docker | Demo fallback | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |

You'll also need to **accept the M5 competition rules** once at https://www.kaggle.com/competitions/m5-forecasting-accuracy/rules so the Kaggle CLI can download.

## First-time setup

```bash
# 1. Backend deps (in a venv)
python3 -m venv .venv
source .venv/bin/activate
pip install -e "apps/api[dev]"

# 2. Frontend deps
npm --prefix apps/web install

# 3. Environment
cp .env.example .env
# edit .env and put your ANTHROPIC_API_KEY in

# 4. Run the API tests (synthetic generator tests run without M5)
cd apps/api && pytest && cd ../..

# 5. Build M5 calibration (~5 min on full dataset, ~30 sec with --sample-skus)
bash scripts/build_m5_calibration.sh --sample-skus 2000   # quick dev
# or
bash scripts/build_m5_calibration.sh                      # full

# 6. Seed sample CSVs
bash scripts/seed_demo.sh

# 7. Run dev servers (web on 3000, api on 8000)
bash scripts/dev.sh
```

## What each Day does (compressed 14-day plan)

See `~/.claude/plans/look-at-the-build-quiet-meteor.md` for the full table. Summary:

- **Day 1 (today)**: Scaffolding ↑
- **Day 2**: Ingestion + assertions schema/business-logic + DQ score skeleton
- **Day 3**: Forecasting v1 (statsforecast classical + Croston/TSB) + backtest harness
- **Day 4**: Inventory math v1 (5 policies + ABC/XYZ + recommend endpoint)
- **Day 5**: Frontend `/upload` → DQ report → `/dashboard` (virtualized table + KPIs)
- **Day 6**: `/sku/[id]` + chat layer v1 (6 tools + tool-use loop + caching) + eval harness
- **Day 7**: Bayesian shrinkage cold-start + M5 pattern classifier
- **Day 8**: Chronos-Bolt + ensemble + conformal calibration
- **Day 9**: Statistical + stationarity DQ components + LLM-explained issues
- **Day 10**: Chat depth (`analyze_dataframe` sandbox + Vega-Lite charts + extended thinking)
- **Day 11**: Multi-period schedule + (s,S) policy + ABC/XYZ heatmap UI
- **Day 12**: Joint replenishment + Settings + Export
- **Day 13**: Hardening (rate limits, Sentry, logs, password gate, a11y)
- **Day 14**: Demo prep — Loom + write-up + dry runs

## How to recreate this in Claude Code

Run these prompts one at a time in the same project. Each session reads `docs/CLAUDE.md` automatically.

- Day 2 prompt: see `docs/PROMPTS.md` (lands in Day 2)
- The architecture plan in `~/.claude/plans/look-at-the-build-quiet-meteor.md` is the source of truth for what each day should produce.

## Layout

```
.
├── apps/
│   ├── api/                 # FastAPI backend
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── synthetic.py
│   │   ├── m5/
│   │   │   ├── build_calibration.py
│   │   │   ├── raw/                     (gitignored, downloaded by script)
│   │   │   └── artifacts/               (committed: calendar_effects.json, etc.)
│   │   ├── ingestion/                   (Day 2)
│   │   ├── assertions/                  (Day 2 schema/business-logic; Day 9 statistical)
│   │   ├── forecasting/                 (Day 3)
│   │   ├── inventory/                   (Day 4)
│   │   ├── llm/                         (Day 6)
│   │   ├── jobs/                        (Day 13 hardening)
│   │   └── tests/
│   └── web/                 # Next.js 14 frontend
│       ├── app/
│       │   ├── page.tsx                 (landing, done)
│       │   ├── upload/                  (Day 2 + Day 5)
│       │   ├── dashboard/               (Day 5)
│       │   └── sku/[id]/                (Day 6)
│       ├── components/                  (Day 5+)
│       ├── lib/
│       └── ... config files
├── data/
│   └── samples/                         (run scripts/seed_demo.sh)
├── evals/                               (Day 6+)
├── scripts/
│   ├── dev.sh
│   ├── seed_demo.sh
│   └── build_m5_calibration.sh
├── docs/
│   └── CLAUDE.md
├── infra/
│   ├── Dockerfile.api
│   └── docker-compose.yml
└── sku_optimizer_build_plan.pdf         (original brief)
```
