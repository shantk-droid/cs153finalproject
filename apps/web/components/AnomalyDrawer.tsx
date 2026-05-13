"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Loader2, Sparkles, TrendingDown, TrendingUp, X } from "lucide-react";
import { VegaLiteEmbed } from "@/components/VegaLiteEmbed";
import { cn } from "@/lib/utils";
import type { AnomalyExplainResponse } from "@/lib/types";

interface Props {
  datasetId: string;
  skuId: string;
  anchorDate?: string | null;
  onClose: () => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  info: "bg-blue-100 text-blue-700",
  warn: "bg-amber-100 text-amber-700",
  crit: "bg-red-100 text-red-700",
};

export function AnomalyDrawer({ datasetId, skuId, anchorDate, onClose }: Props) {
  const [data, setData] = useState<AnomalyExplainResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`/api/datasets/${datasetId}/skus/${encodeURIComponent(skuId)}/anomaly_explain`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ anchor_date: anchorDate ?? null, severity_threshold: 2.5 }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json() as Promise<AnomalyExplainResponse>;
      })
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "load failed"))
      .finally(() => setLoading(false));
  }, [datasetId, skuId, anchorDate]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-stretch justify-end bg-black/40 backdrop-blur-sm"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl overflow-y-auto bg-card shadow-2xl"
      >
        <header className="flex items-center justify-between border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <div>
              <p className="text-xs uppercase tracking-widest text-muted-foreground">
                Anomaly explainer
              </p>
              <h2 className="font-mono text-sm font-semibold">{skuId}</h2>
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="space-y-4 p-4">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Investigating with tools…
            </div>
          )}
          {error && (
            <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}
          {data && (
            <>
              {data.fallback && (
                <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  <strong>Heuristic fallback:</strong> {data.error ?? "LLM agent unavailable."}
                </div>
              )}

              {data.detected.length === 0 ? (
                <div className="rounded border bg-muted/30 px-3 py-3 text-sm">
                  {data.explanation}
                </div>
              ) : (
                <>
                  <section>
                    <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
                      Detected events
                    </p>
                    <ul className="mt-2 space-y-1">
                      {data.detected.map((e, i) => (
                        <li
                          key={i}
                          className="flex items-center justify-between rounded border bg-background px-3 py-2 text-sm"
                        >
                          <div className="flex items-center gap-2">
                            {e.direction === "spike" ? (
                              <TrendingUp className="h-3.5 w-3.5 text-red-600" />
                            ) : (
                              <TrendingDown className="h-3.5 w-3.5 text-amber-600" />
                            )}
                            <span className="font-mono text-xs">{e.date}</span>
                            <span className="text-muted-foreground">
                              {e.value.toFixed(0)} vs {e.baseline_mean.toFixed(0)}
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                "rounded px-1.5 py-0.5 text-[11px] font-medium",
                                SEVERITY_COLOR[e.severity],
                              )}
                            >
                              {e.severity}
                            </span>
                            <span className="font-mono text-xs tabular-nums text-muted-foreground">
                              z={e.magnitude_z >= 0 ? "+" : ""}
                              {e.magnitude_z.toFixed(1)}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>

                  <section>
                    <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
                      Explanation
                    </p>
                    <div className="mt-1 rounded border-l-2 border-primary bg-primary/5 px-3 py-3 text-sm leading-relaxed">
                      {data.explanation}
                    </div>
                  </section>

                  <section>
                    <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
                      Demand series
                    </p>
                    <div className="mt-1 rounded border bg-background p-2">
                      <VegaLiteEmbed spec={data.chart_spec} />
                    </div>
                  </section>

                  {data.tool_calls.length > 0 && (
                    <section>
                      <details>
                        <summary className="cursor-pointer text-[11px] uppercase tracking-widest text-muted-foreground hover:text-foreground">
                          Tool calls ({data.tool_calls.length})
                        </summary>
                        <ul className="mt-2 space-y-1 text-xs">
                          {data.tool_calls.map((tc, i) => (
                            <li key={i} className="rounded border-l-2 border-muted bg-muted/20 px-2 py-1">
                              <span className="font-mono">{tc.name}</span>
                              <span className="ml-2 text-muted-foreground">
                                {tc.duration_ms}ms{tc.error ? ` · ${tc.error}` : ""}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </details>
                    </section>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
