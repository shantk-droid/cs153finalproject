"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface Comparison {
  metric: string;
  user_value: number;
  m5_p1: number;
  m5_p25: number;
  m5_p50: number;
  m5_p75: number;
  m5_p99: number;
  position:
    | "below_p1" | "p1_to_p5" | "p5_to_p25" | "p25_to_p75"
    | "p75_to_p95" | "p95_to_p99" | "above_p99";
  percentile_band: [number, number];
  matched_dept: string;
}

interface CalibrationData {
  sku_id: string;
  category: string | null;
  calibration_version: string | null;
  metrics: Record<string, number>;
  comparisons: Comparison[];
  note?: string;
}

const METRIC_LABEL: Record<string, string> = {
  cv_demand: "Demand variability (CV)",
  intermittency_rate: "Intermittency (% zeros)",
  seasonality_strength: "Seasonality strength",
  trend_slope_pct: "Trend slope (|%/period|)",
  regime_shift_score: "Regime-shift score",
};

function positionStyle(p: Comparison["position"]): { bg: string; label: string } {
  if (p === "below_p1" || p === "above_p99")
    return { bg: "bg-destructive/15 text-destructive", label: "outlier" };
  if (p === "p1_to_p5" || p === "p95_to_p99")
    return { bg: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-300", label: "tail" };
  return { bg: "bg-muted text-muted-foreground", label: "in band" };
}

interface Props {
  datasetId: string;
  skuId: string;
}

export function CalibrationCard({ datasetId, skuId }: Props) {
  const [data, setData] = useState<CalibrationData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    const timeoutId = setTimeout(() => ctrl.abort(), 10_000);

    setLoading(true);
    setError(null);
    (async () => {
      try {
        const r = await fetch(
          `/api/datasets/${encodeURIComponent(datasetId)}/skus/${encodeURIComponent(skuId)}/calibration`,
          { signal: ctrl.signal },
        );
        if (!r.ok) throw new Error(`API ${r.status}`);
        setData(await r.json());
      } catch (e) {
        if ((e as Error).name === "AbortError") {
          setError("Calibration request timed out.");
        } else {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        clearTimeout(timeoutId);
        setLoading(false);
      }
    })();
    return () => {
      clearTimeout(timeoutId);
      ctrl.abort();
    };
  }, [datasetId, skuId, retryToken]);

  if (loading) {
    return (
      <div className="rounded-lg border bg-card p-4 text-xs text-muted-foreground">
        Loading M5 calibration comparison…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-lg border bg-card p-4 text-xs text-muted-foreground">
        Couldn&apos;t load M5 calibration ({error}).{" "}
        <button
          type="button"
          onClick={() => setRetryToken((t) => t + 1)}
          className="text-primary hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!data || data.comparisons.length === 0) {
    return null;
  }

  return (
    <details className="group rounded-lg border bg-card p-4">
      <summary className="cursor-pointer space-y-1">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold">M5 Walmart calibration</h3>
          <p className="text-xs text-muted-foreground">
            matched to <span className="font-mono">{data.comparisons[0]?.matched_dept}</span>
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          Where this SKU sits vs the M5 reference distribution (click to expand)
        </p>
      </summary>
      <div className="mt-3 space-y-2">
        {data.comparisons.map((c) => {
          const style = positionStyle(c.position);
          return (
            <div key={c.metric} className="rounded-md border p-2">
              <div className="flex items-baseline justify-between">
                <p className="text-xs font-medium">{METRIC_LABEL[c.metric] ?? c.metric}</p>
                <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium uppercase", style.bg)}>
                  {style.label}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                you: <span className="font-mono tabular-nums">{c.user_value.toFixed(3)}</span>
                {" · "}M5 p25/p50/p75:{" "}
                <span className="font-mono tabular-nums">
                  {c.m5_p25.toFixed(3)} / {c.m5_p50.toFixed(3)} / {c.m5_p75.toFixed(3)}
                </span>
              </p>
              <div className="mt-1.5 h-1.5 rounded bg-muted">
                {(() => {
                  const lo = c.m5_p1, hi = c.m5_p99, span = Math.max(1e-9, hi - lo);
                  const x = Math.max(0, Math.min(1, (c.user_value - lo) / span));
                  return (
                    <div
                      className="relative h-full rounded bg-primary/40"
                      style={{ width: `${(x * 100).toFixed(0)}%` }}
                    />
                  );
                })()}
              </div>
              <p className="mt-1 text-[10px] text-muted-foreground">
                in M5 p{c.percentile_band[0]}–p{c.percentile_band[1]}
              </p>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-[10px] text-muted-foreground">
        calibration version: <span className="font-mono">{data.calibration_version ?? "—"}</span>
      </p>
    </details>
  );
}
