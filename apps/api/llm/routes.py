"""POST /datasets/{id}/chat — SSE streaming chat endpoint with rate limit.

Plus three small POST endpoints under /datasets/{id}/insights/* that LLM-enrich
the heuristic insights the UI already computed. They gracefully degrade to an
empty list when no Anthropic key is set, so the UI keeps showing heuristics.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from apps.api.config import get_settings
from apps.api.db import dataset_path
from apps.api.llm.cost_ledger import BudgetExceededError, check_budget
from apps.api.llm.insights import (
    LlmInsight,
    SkuNarrative,
    panel_insights,
    sku_narrative,
    supplier_insights,
)
from apps.api.llm.loop import stream_chat_sse
from apps.api.llm.orchestrator import run_multi_agent
from apps.api.llm.schemas import ChatRequest

router = APIRouter(prefix="/datasets", tags=["chat"])

# Per the plan: 30 requests / minute / IP on /chat (cost control).
limiter = Limiter(key_func=get_remote_address, enabled=os.environ.get("RATELIMIT_DISABLED") != "1")


@router.post("/{dataset_id}/chat")
@limiter.limit("30/minute")
async def chat(
    request: Request,
    dataset_id: str,
    body: ChatRequest,
    single: int = 0,
):
    """SSE chat endpoint.

    By default routes through the multi-agent orchestrator (Router → single OR
    Router → Planner → specialists). Pass `?single=1` to force the legacy
    single-agent path — used by the existing eval harness to pin regression coverage.
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    settings = get_settings()
    try:
        check_budget(settings.data_path, settings.llm_daily_usd_budget)
    except BudgetExceededError as e:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "budget_exceeded",
                "message": str(e),
                "spent_usd": e.spent_usd,
                "budget_usd": e.budget_usd,
            },
        )

    user_turns = [m.model_dump() for m in body.messages]

    if single:
        async def event_stream():
            async for event in stream_chat_sse(dataset_id, user_turns):
                yield event
    else:
        # Multi-agent default. The orchestrator's Router auto-falls-back to single-agent
        # for shallow questions, so this is the right default.
        last_user_content = user_turns[-1]["content"] if user_turns else ""
        async def event_stream():
            async for event in run_multi_agent(dataset_id, last_user_content):
                yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------- LLM-enriched insights ----------


class HeuristicInsight(BaseModel):
    tone: str
    text: str


class PanelInsightsRequest(BaseModel):
    summary: dict
    heuristics: list[HeuristicInsight] = []


class SupplierInsightsRequest(BaseModel):
    summary: dict
    heuristics: list[HeuristicInsight] = []


class SkuInsightsRequest(BaseModel):
    sku: dict
    heuristics: list[HeuristicInsight] = []


class InsightsResponse(BaseModel):
    insights: list[LlmInsight]


class SkuInsightsResponse(BaseModel):
    narrative: SkuNarrative | None


@router.post("/{dataset_id}/insights/panel", response_model=InsightsResponse)
@limiter.limit("60/minute")
async def post_panel_insights(
    request: Request,
    dataset_id: str,
    body: PanelInsightsRequest,
) -> InsightsResponse:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    insights = panel_insights(body.summary, [h.model_dump() for h in body.heuristics])
    return InsightsResponse(insights=insights)


@router.post("/{dataset_id}/insights/suppliers", response_model=InsightsResponse)
@limiter.limit("60/minute")
async def post_supplier_insights(
    request: Request,
    dataset_id: str,
    body: SupplierInsightsRequest,
) -> InsightsResponse:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    insights = supplier_insights(body.summary, [h.model_dump() for h in body.heuristics])
    return InsightsResponse(insights=insights)


@router.post("/{dataset_id}/skus/{sku_id}/insights", response_model=SkuInsightsResponse)
@limiter.limit("60/minute")
async def post_sku_insights(
    request: Request,
    dataset_id: str,
    sku_id: str,
    body: SkuInsightsRequest,
) -> SkuInsightsResponse:
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    body.sku.setdefault("sku_id", sku_id)
    narrative = sku_narrative(body.sku, [h.model_dump() for h in body.heuristics])
    return SkuInsightsResponse(narrative=narrative)


# ---------- Scheduled briefing ----------


@router.get("/{dataset_id}/briefing")
async def get_briefing(dataset_id: str) -> dict:
    """Return today's cached briefing JSON, or a stub if not yet generated.

    The cron job (`scheduled_briefing` in modal_app.py) refreshes this daily at 14:00 UTC.
    On a fresh deployment or before the cron has fired, this returns `{stub: true}` so the
    dashboard renders a "briefing generates at 9am PT" placeholder.
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.llm.briefing import read_cached_briefing
    cached = read_cached_briefing(dataset_id)
    if cached is None:
        from datetime import date
        return {
            "dataset_id": dataset_id,
            "date": date.today().isoformat(),
            "text": "",
            "stub": True,
            "reason": "briefing not yet generated for today",
            "usage_usd": 0.0,
        }
    return cached


@router.get("/{dataset_id}/tour")
async def get_tour_route(dataset_id: str) -> dict:
    """Return the cached LLM-generated dashboard tour, or generate it on demand.

    Cached for 30 days at `{data_path}/llm_insights/tour.{dataset_id}.json`. Falls back
    to a canned heuristic tour when the API key is missing or the LLM call fails — so the
    frontend modal always has 4 steps to render.
    """
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    from apps.api.llm.tour import get_or_generate_tour
    return get_or_generate_tour(dataset_id)


@router.post("/{dataset_id}/briefing/refresh")
@limiter.limit("4/minute")
async def post_briefing_refresh(request: Request, dataset_id: str) -> dict:
    """Force-regenerate today's briefing. Limited to 4/min/IP — refresh is expensive
    (one Planner run ~$0.10). Mostly for testing the cron locally."""
    if not dataset_path(dataset_id).exists():
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found")
    settings = get_settings()
    try:
        check_budget(settings.data_path, settings.llm_daily_usd_budget)
    except BudgetExceededError as e:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "budget_exceeded",
                "message": str(e),
                "spent_usd": e.spent_usd,
                "budget_usd": e.budget_usd,
            },
        )
    from apps.api.llm.briefing import generate_briefing
    return generate_briefing(dataset_id)
