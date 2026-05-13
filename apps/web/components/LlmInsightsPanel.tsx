"use client";

import { useEffect, useState } from "react";
import { InsightsPanel, type Insight } from "@/components/InsightsPanel";
import {
  fetchPanelInsights,
  fetchSupplierInsights,
  type HeuristicInsightInput,
} from "@/lib/api-client";
import type { LlmInsight } from "@/lib/types";

type Variant = "panel" | "supplier";

interface Props {
  datasetId: string;
  variant: Variant;
  /** Heuristic insights computed by the page's deterministic helper. Render immediately. */
  heuristics: Insight[];
  /** Compact JSON-able context the LLM needs to extend the heuristics. */
  summary: Record<string, unknown>;
  /** Optional title override. */
  title?: string;
}

/**
 * Shows the heuristic insights instantly, then fires a single POST to the LLM
 * enrichment endpoint and appends 2-3 LLM-authored bullets when they arrive.
 *
 * If the request fails or returns no insights (e.g. no Anthropic key), the
 * panel keeps showing heuristics — no error UI, no flicker.
 */
export function LlmInsightsPanel({ datasetId, variant, heuristics, summary, title }: Props) {
  const [llm, setLlm] = useState<LlmInsight[]>([]);
  const summaryKey = JSON.stringify(summary);

  useEffect(() => {
    const ctrl = new AbortController();
    const heuristicsPayload: HeuristicInsightInput[] = heuristics.map((h) => ({
      tone: h.tone ?? "info",
      text: h.text,
    }));
    const fetcher = variant === "panel" ? fetchPanelInsights : fetchSupplierInsights;
    fetcher(datasetId, summary, heuristicsPayload, ctrl.signal)
      .then((r) => setLlm(r.insights ?? []))
      .catch(() => {
        /* graceful: heuristics already render */
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, variant, summaryKey]);

  const merged: Insight[] = [
    ...heuristics.map((h) => ({ ...h, source: "heuristic" as const })),
    ...llm.map((l) => ({ tone: l.tone, text: l.text, source: "llm" as const })),
  ];

  return <InsightsPanel title={title} insights={merged} />;
}
