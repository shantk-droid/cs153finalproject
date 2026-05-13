"""Modal deployment for the FastAPI service.

Deploy:
    modal token new                          # one-time, opens browser
    modal secret create inventory-secrets ANTHROPIC_API_KEY=sk-ant-...
    modal deploy apps/api/modal_app.py

Modal will print a public HTTPS URL like
    https://<account>--inventory-optimizer-fastapi-app.modal.run
Set that URL as NEXT_PUBLIC_API_URL in Vercel project settings.

Storage:
- DuckDB dataset files persist in a Modal Volume mounted at /root/data.
- M5 calibration artifacts ship with the image (read-only).
"""

from __future__ import annotations

import modal

APP_NAME = "inventory-optimizer"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgomp1")
    .pip_install(
        # Core
        "fastapi>=0.115",
        "uvicorn[standard]>=0.30",
        "pydantic>=2.7",
        "pydantic-settings>=2.4",
        "python-multipart>=0.0.9",
        "httpx>=0.27",
        # Data
        "pandas>=2.2",
        "numpy>=1.26,<2.0",
        "scipy>=1.13",
        "duckdb>=1.0",
        "openpyxl>=3.1",
        "pyarrow>=16",
        # Forecasting
        "statsforecast>=1.7",
        "lightgbm>=4.3",
        "hierarchicalforecast>=0.4",  # Day 11 reconciliation
        # Foundation forecast (Day 8) — torch is heavy, but small Chronos-Bolt CPU inference is fine
        "torch>=2.2",
        "chronos-forecasting>=2.0",
        # LLM
        "anthropic>=0.34",
        # Observability (Day 13)
        "structlog>=24.0",
        "sentry-sdk[fastapi]>=2.0",
        # Misc
        "python-dotenv>=1.0",
        "slowapi>=0.1.9",
        "rich>=13.7",
    )
    .add_local_dir("apps/api", remote_path="/root/apps/api", copy=True)
)

data_volume = modal.Volume.from_name(f"{APP_NAME}-data", create_if_missing=True)

app = modal.App(APP_NAME, image=image)


@app.function(
    volumes={"/root/data": data_volume},
    secrets=[modal.Secret.from_name("inventory-secrets")],
    timeout=300,
    memory=4096,
    cpu=2.0,
    # Keep one container warm so first-visit users don't hit a 10–30 s cold start
    # while waiting for the demo dataset to render. Cost: ~one tiny CPU container's
    # idle hour rate. Worth it for portfolio + investor demo links.
    min_containers=1,
    # Cap at one container. Datasets created in one container weren't visible
    # to a sibling without an explicit volume.reload() — symptom: dashboard
    # tabs returning 404 right after a successful demo POST. Single-container
    # is fine for portfolio traffic; FastAPI handles concurrent requests
    # asynchronously within the one container.
    max_containers=1,
    scaledown_window=300,
)
@modal.asgi_app()
def fastapi_app():
    import os
    import sys

    sys.path.insert(0, "/root")
    os.environ.setdefault("DATA_DIR", "/root/data/datasets")
    os.environ.setdefault("M5_ARTIFACTS_DIR", "./m5/artifacts")

    from apps.api.main import app as fastapi_instance

    return fastapi_instance


# 14:00 UTC = 6am Pacific (PST) / 7am Pacific (PDT). Briefing is ready by the time users log in.
# Cost: roughly $0.10–$0.50/dataset/day depending on Planner depth; with one demo dataset it's
# under $1/month. The cron is gated by ANTHROPIC_API_KEY — if the secret is missing, the
# briefing job exits early with a stub.
@app.function(
    volumes={"/root/data": data_volume},
    secrets=[modal.Secret.from_name("inventory-secrets")],
    timeout=1800,
    memory=4096,
    cpu=2.0,
    schedule=modal.Cron("0 14 * * *"),
)
def scheduled_briefing():
    """Daily cron: refresh today's briefing for every dataset on the volume.

    Runs the multi-agent Planner against each dataset and writes the output to
    `llm_insights/briefing.{dataset_id}.{YYYY-MM-DD}.json`. Idempotent — re-running on the
    same UTC day overwrites the same file. The dashboard reads the cached file with no
    LLM call on page load.
    """
    import os
    import sys

    sys.path.insert(0, "/root")
    os.environ.setdefault("DATA_DIR", "/root/data/datasets")
    os.environ.setdefault("M5_ARTIFACTS_DIR", "./m5/artifacts")

    from apps.api.llm.briefing import generate_all_briefings

    return generate_all_briefings()
