"""Sentry init + structlog setup + request logging middleware.

Wired in by `main.py`. Idempotent: if SENTRY_DSN is empty, Sentry stays off.
Structlog always runs; output is JSON when `LOG_FORMAT=json`, otherwise human-readable.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any

import structlog
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def _add_request_id(_logger: Any, _name: str, event_dict: dict) -> dict:
    rid = _request_id.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging() -> None:
    log_format = os.environ.get("LOG_FORMAT", "human").lower()
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        _add_request_id,
    ]
    if log_format == "json":
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        processors = shared_processors + [structlog.dev.ConsoleRenderer(colors=False)]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")


def init_sentry(dsn: str | None, environment: str = "dev") -> bool:
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
        integrations=[FastApiIntegration(), StarletteIntegration()],
    )
    return True


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Tag every request with a generated request_id, log start+end with duration+status."""

    async def dispatch(self, request: Request, call_next):
        import uuid
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = _request_id.set(rid)
        log = structlog.get_logger("api")
        log = log.bind(method=request.method, path=request.url.path)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            log.error("request_failed", duration_ms=duration_ms, error=str(exc), error_type=type(exc).__name__)
            _record_request_latency(request, duration_ms, status=500)
            raise
        finally:
            _request_id.reset(token)
        duration_ms = int((time.perf_counter() - start) * 1000)
        log.info("request_completed", status=response.status_code, duration_ms=duration_ms)
        response.headers["x-request-id"] = rid
        _record_request_latency(request, duration_ms, status=response.status_code)
        return response


def _record_request_latency(request: Request, duration_ms: int, *, status: int) -> None:
    """Resolve the matched route template (or fall back to the raw URL path) and record a latency sample.

    Route templates collapse `/datasets/abc123/quality` and `/datasets/xyz789/quality` into a single
    `/datasets/{id}/quality` bucket so /health doesn't see cardinality explode per-dataset.
    """
    route = request.scope.get("route")
    route_template = getattr(route, "path", None) or request.url.path
    record_latency(f"{request.method} {route_template}", duration_ms, status=status)


_LATENCY_HISTORY: list[dict] = []
_MAX_HISTORY = 100


def record_latency(operation: str, duration_ms: int, **fields: Any) -> None:
    """Record a latency sample for the /health page. Thread-unsafe but good enough for v1."""
    entry: dict = {"operation": operation, "duration_ms": duration_ms, "ts": time.time()}
    entry.update(fields)
    _LATENCY_HISTORY.append(entry)
    if len(_LATENCY_HISTORY) > _MAX_HISTORY:
        del _LATENCY_HISTORY[0:len(_LATENCY_HISTORY) - _MAX_HISTORY]


def latency_summary() -> dict:
    if not _LATENCY_HISTORY:
        return {"n_samples": 0}
    durations = [e["duration_ms"] for e in _LATENCY_HISTORY]
    by_op: dict[str, list[int]] = {}
    for e in _LATENCY_HISTORY:
        by_op.setdefault(e["operation"], []).append(e["duration_ms"])
    summary = {
        "n_samples": len(_LATENCY_HISTORY),
        "p50_ms": int(sorted(durations)[len(durations) // 2]),
        "p95_ms": int(sorted(durations)[int(len(durations) * 0.95)]),
        "by_operation": {op: {"n": len(v), "mean_ms": int(sum(v) / len(v))} for op, v in by_op.items()},
    }
    return summary


def install(app: FastAPI, dsn: str | None, environment: str) -> None:
    """One-shot installer called from main.py."""
    configure_logging()
    sentry_on = init_sentry(dsn, environment)
    log = structlog.get_logger("api")
    log.info("observability_installed", sentry=sentry_on, environment=environment)
    app.add_middleware(RequestLoggingMiddleware)
