from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from apps.api import observability
from apps.api.config import get_settings
from apps.api.forecasting.routes import router as forecasting_router
from apps.api.ingestion.routes import router as datasets_router
from apps.api.inventory.routes import router as inventory_router
from apps.api.llm.routes import router as llm_router

settings = get_settings()

# Rate limiter — applied to specific routes via decorators below + middleware for response.
limiter = Limiter(key_func=get_remote_address, default_limits=[])


app = FastAPI(
    title="Inventory Optimizer API",
    version="0.2.0",
    description="Ingestion, forecasting, inventory math, and LLM tool-use chat for SKU panels.",
)

observability.install(app, dsn=settings.sentry_dsn, environment=os.environ.get("ENV", "dev"))

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets_router)
app.include_router(forecasting_router)
app.include_router(inventory_router)
app.include_router(llm_router)


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    m5_calibration_version: str | None
    m5_artifacts_present: bool
    m5_artifacts: list[str]
    sentry_enabled: bool
    anthropic_configured: bool
    latency: dict[str, Any]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    artifacts_dir = settings.m5_artifacts_path
    version_file = artifacts_dir / "VERSION"
    m5_version = version_file.read_text().strip() if version_file.exists() else None
    artifacts_present = artifacts_dir.exists() and any(artifacts_dir.iterdir()) if artifacts_dir.exists() else False
    artifacts = sorted(p.name for p in artifacts_dir.iterdir()) if artifacts_present else []
    return HealthResponse(
        status="ok",
        version=app.version,
        environment=os.environ.get("ENV", "dev"),
        m5_calibration_version=m5_version,
        m5_artifacts_present=artifacts_present,
        m5_artifacts=artifacts,
        sentry_enabled=bool(settings.sentry_dsn),
        anthropic_configured=bool(settings.anthropic_api_key),
        latency=observability.latency_summary(),
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"name": app.title, "version": app.version, "docs": "/docs", "health": "/health"}
