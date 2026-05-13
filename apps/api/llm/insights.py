"""LLM-enriched insights for the Forecasts page, Suppliers page, and individual SKUs.

Falls back to heuristic-only insights when no Anthropic API key is configured —
the UI receives an empty list and renders the heuristic insights it already has.

Caching: each call is keyed off a content hash of the input context. Repeat
visits to the same dashboard hit the disk cache and cost $0.

Cost cap: each call uses ≤ 600 output tokens. Three call sites × ~$0.005/call
puts a typical dashboard at < $0.02 even with cold caches.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from apps.api.config import get_settings


class LlmInsight(BaseModel):
    tone: Literal["info", "warn", "good"]
    text: str
    source: Literal["heuristic", "llm"] = "llm"


class SkuNarrative(BaseModel):
    paragraph: str
    bullets: list[LlmInsight]
    source: Literal["heuristic", "llm"] = "llm"


# ---------- prompts ----------

PANEL_SYSTEM = """You are an inventory operations advisor reviewing an SKU panel.
You'll receive a JSON object with two parts:
  - "panel": aggregate stats (counts by status / class, top suppliers, etc.)
  - "heuristics": insights we already computed deterministically

Write 2-3 SHORT actionable insights (each 1-2 sentences) that EXTEND the heuristics —
- lead with a concrete action ("Prioritize", "Consider", "Watch")
- cite specific numbers from the panel
- tell the reader WHAT to do, not just what's wrong
- avoid restating the heuristics verbatim or hedging ("might want to consider")

Output strictly as a JSON array, no prose, no markdown:
[{"tone": "warn|info|good", "text": "..."}, ...]"""

SUPPLIER_SYSTEM = """You are reviewing a supplier scorecard for an inventory team.
You'll receive a JSON object with:
  - "suppliers": list of suppliers with OTIF, lead-time mean/std, revenue, payment terms
  - "heuristics": insights we already computed deterministically

Write 2-3 SHORT supplier-focused recommendations (each 1-2 sentences):
- name suppliers explicitly when calling them out
- weave in commercial actions: backup sourcing, expediting clauses, lead-time padding
- cite specific numbers (OTIF %, LT std, revenue share)

Output strictly as a JSON array, no prose, no markdown:
[{"tone": "warn|info|good", "text": "..."}, ...]"""

SKU_SYSTEM = """You are an inventory analyst writing a one-paragraph briefing
for a single SKU plus 2-3 follow-up bullet recommendations.
Input JSON has the SKU's forecast, recommendation policy, recent demand, and
heuristic insights already computed.

Output strictly:
{
  "paragraph": "<3-5 sentence narrative — current status, recent trend, next planned order, biggest risk>",
  "bullets": [{"tone": "warn|info|good", "text": "<concrete action>"}, ...]
}

Style:
- The paragraph speaks to the planner: 'On-hand 417 covers ~30 days; the next order…'
- Bullets are imperative ('Expedite if on-hand drops below…', 'Raise service level on this SKU because…')
- No hedging; cite specific numbers
- No prose outside the JSON, no markdown"""


# ---------- shared infra ----------


def _cache_dir() -> Path:
    base = get_settings().data_path / "llm_insights"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_key(context: dict) -> str:
    payload = json.dumps(context, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def _read_cache(prefix: str, key: str) -> Any | None:
    p = _cache_dir() / f"{prefix}.{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _write_cache(prefix: str, key: str, value: Any) -> None:
    try:
        p = _cache_dir() / f"{prefix}.{key}.json"
        p.write_text(json.dumps(value, indent=2, default=str))
    except Exception:
        pass


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    return text


def _call_claude(system: str, payload: dict, max_tokens: int = 600) -> str | None:
    """Single-shot Anthropic call. Returns None when no key is configured or any error occurs."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
        )
        return "".join(b.text for b in response.content if b.type == "text")
    except Exception:
        return None


def _parse_insights(raw: str | None) -> list[LlmInsight]:
    if not raw:
        return []
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return []
    out: list[LlmInsight] = []
    for item in parsed if isinstance(parsed, list) else []:
        if not isinstance(item, dict):
            continue
        tone = item.get("tone", "info")
        text = item.get("text", "")
        if tone not in ("info", "warn", "good") or not text:
            continue
        out.append(LlmInsight(tone=tone, text=str(text), source="llm"))
    return out[:3]


# ---------- public surface ----------


def panel_insights(panel_summary: dict, heuristics: list[dict], use_cache: bool = True) -> list[LlmInsight]:
    """LLM-enriched insights for the Forecasts page or Overview tab.

    `panel_summary` should be a small JSON-able dict (counts, top categories, etc.).
    `heuristics` is whatever the deterministic helper already produced — passed as
    context so the LLM extends rather than duplicates them.
    """
    payload = {"panel": panel_summary, "heuristics": heuristics}
    key = _cache_key({"kind": "panel", **payload})
    if use_cache:
        cached = _read_cache("panel", key)
        if cached is not None:
            return [LlmInsight.model_validate(x) for x in cached]

    raw = _call_claude(PANEL_SYSTEM, payload)
    insights = _parse_insights(raw)
    if insights and use_cache:
        _write_cache("panel", key, [i.model_dump() for i in insights])
    return insights


def supplier_insights(supplier_summary: dict, heuristics: list[dict], use_cache: bool = True) -> list[LlmInsight]:
    """LLM-enriched supplier-tab recommendations."""
    payload = {"suppliers": supplier_summary, "heuristics": heuristics}
    key = _cache_key({"kind": "supplier", **payload})
    if use_cache:
        cached = _read_cache("supplier", key)
        if cached is not None:
            return [LlmInsight.model_validate(x) for x in cached]

    raw = _call_claude(SUPPLIER_SYSTEM, payload)
    insights = _parse_insights(raw)
    if insights and use_cache:
        _write_cache("supplier", key, [i.model_dump() for i in insights])
    return insights


def sku_narrative(sku_context: dict, heuristics: list[dict], use_cache: bool = True) -> SkuNarrative | None:
    """Per-SKU narrative paragraph + recommendations."""
    payload = {"sku": sku_context, "heuristics": heuristics}
    key = _cache_key({"kind": "sku", **payload})
    if use_cache:
        cached = _read_cache("sku", key)
        if cached is not None:
            try:
                return SkuNarrative.model_validate(cached)
            except Exception:
                pass

    raw = _call_claude(SKU_SYSTEM, payload, max_tokens=900)
    if not raw:
        return None
    try:
        parsed = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError:
        return None

    paragraph = str(parsed.get("paragraph", "")).strip()
    bullets_raw = parsed.get("bullets", []) if isinstance(parsed, dict) else []
    bullets: list[LlmInsight] = []
    for item in bullets_raw:
        if not isinstance(item, dict):
            continue
        tone = item.get("tone", "info")
        text = item.get("text", "")
        if tone not in ("info", "warn", "good") or not text:
            continue
        bullets.append(LlmInsight(tone=tone, text=str(text), source="llm"))
    if not paragraph and not bullets:
        return None

    narrative = SkuNarrative(paragraph=paragraph, bullets=bullets[:3], source="llm")
    if use_cache:
        _write_cache("sku", key, narrative.model_dump())
    return narrative
