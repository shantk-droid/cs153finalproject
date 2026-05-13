import Link from "next/link";
import { notFound } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { AnomalyExplainerButton } from "@/components/AnomalyExplainerButton";
import { AuditFooter } from "@/components/AuditFooter";
import { CalibrationCard } from "@/components/CalibrationCard";
import { ConformalCoverageCard } from "@/components/ConformalCoverageCard";
import { DecompositionTabs } from "@/components/DecompositionTabs";
import { EnsembleNarrative } from "@/components/EnsembleNarrative";
import { ForecastChart } from "@/components/ForecastChart";
import { OrderScheduleTable } from "@/components/OrderScheduleTable";
import { RecommendationCard } from "@/components/RecommendationCard";
import { ScenarioSliders } from "@/components/ScenarioSliders";
import { SkuHeaderBlock } from "@/components/SkuHeaderBlock";
import { SkuNarrativeCard } from "@/components/SkuNarrativeCard";
import { serverFetch } from "@/lib/api-server";
import { deriveSkuHeuristics, summarizeSku } from "@/lib/insights";
import type { Forecast, Recommendation } from "@/lib/types";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string; skuId: string }>;
}

interface HistoryRow {
  date: string;
  demand: number;
}

interface SkuRowLite {
  sku_id: string;
  category: string | null;
  abc_class: "A" | "B" | "C";
  xyz_class: "X" | "Y" | "Z";
}

async function fetchJson<T>(method: "GET" | "POST", path: string): Promise<T | null> {
  return serverFetch<T>(path, {
    method,
    headers: method === "POST" ? { "content-type": "application/json" } : {},
    body: method === "POST" ? "{}" : undefined,
  });
}

function projectedStockoutCount(rec: Recommendation): number {
  if (!rec.schedule) return 0;
  return rec.schedule.filter((e) => e.action === "stockout").length;
}

export default async function SkuDetailPage({ params }: Props) {
  const { id, skuId } = await params;
  const decoded = decodeURIComponent(skuId);

  const [forecast, rec, history, allRows] = await Promise.all([
    fetchJson<Forecast>(
      "POST",
      `/datasets/${encodeURIComponent(id)}/skus/${encodeURIComponent(decoded)}/forecast?horizon=12`,
    ),
    fetchJson<Recommendation>(
      "POST",
      `/datasets/${encodeURIComponent(id)}/skus/${encodeURIComponent(decoded)}/recommend`,
    ),
    fetchJson<HistoryRow[]>(
      "GET",
      `/datasets/${encodeURIComponent(id)}/skus/${encodeURIComponent(decoded)}/history?last_n=104`,
    ),
    fetchJson<SkuRowLite[]>(
      "GET",
      `/datasets/${encodeURIComponent(id)}/skus?limit=2000`,
    ),
  ]);
  if (!forecast || !rec) notFound();
  const historyRows: HistoryRow[] = history ?? [];

  const meta = (allRows ?? []).find((r) => r.sku_id === decoded);
  const stockouts = projectedStockoutCount(rec);
  const isColdStart = forecast.diagnostics.n_obs < 90 || forecast.diagnostics.prior_weight > 0.2;
  const skuHeuristics = deriveSkuHeuristics(forecast, rec, historyRows);
  const skuSummary = summarizeSku(forecast, rec, historyRows, meta ?? null);

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <Link
        href={`/dashboard/${id}/forecasts`}
        className="text-xs text-muted-foreground underline-offset-4 hover:underline"
      >
        ← Forecasts
      </Link>

      <SkuHeaderBlock
        skuId={decoded}
        category={meta?.category ?? null}
        abc={(meta?.abc_class ?? rec.abc_class) as "A" | "B" | "C"}
        xyz={(meta?.xyz_class ?? rec.xyz_class) as "X" | "Y" | "Z"}
        history={historyRows}
        forecast={forecast}
        rec={rec}
      />

      {isColdStart && (
        <div className="inline-flex items-center gap-2 rounded-full border border-blue-300 bg-blue-50 px-3 py-1 text-xs text-blue-800 dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-300">
          Cold-start: forecast leans on category prior
          {meta?.category && ` (${meta.category})`}
          {forecast.diagnostics.prior_weight > 0 &&
            ` · prior weight ${(forecast.diagnostics.prior_weight * 100).toFixed(0)}%`}
        </div>
      )}

      <SkuNarrativeCard
        datasetId={id}
        skuId={decoded}
        sku={skuSummary}
        heuristics={skuHeuristics.map((h) => ({ tone: h.tone ?? "info", text: h.text }))}
      />

      {stockouts > 0 && (
        <div className="flex items-start gap-2 rounded-md border border-yellow-500/50 bg-yellow-500/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-yellow-600 dark:text-yellow-400" aria-hidden />
          <div>
            <p className="font-medium">
              Schedule projects {stockouts} stockout {stockouts === 1 ? "period" : "periods"} in the next{" "}
              {forecast.horizon_periods} {forecast.frequency === "D" ? "days" : forecast.frequency === "W" ? "weeks" : "months"}.
            </p>
            <p className="mt-0.5 text-xs text-foreground/75">
              Consider raising service level, shortening lead time, or expediting the next order.
            </p>
          </div>
        </div>
      )}

      <section className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <div className="space-y-3 rounded-lg border bg-card p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold">
                Forecast — next {forecast.horizon_periods} periods ({forecast.frequency})
              </h2>
              <div className="flex items-center gap-3">
                <p className="text-xs text-muted-foreground">
                  total: {forecast.point.reduce((a, b) => a + b, 0).toFixed(0)} units
                </p>
                <AnomalyExplainerButton datasetId={id} skuId={decoded} />
              </div>
            </div>
            <ForecastChart history={historyRows} forecast={forecast} />
          </div>

          {rec.schedule && rec.schedule.length > 0 && (
            <div className="space-y-3 rounded-lg border bg-card p-5">
              <div className="flex items-baseline justify-between">
                <h2 className="text-sm font-semibold">Projected order schedule</h2>
                <p className="text-xs text-muted-foreground">
                  {forecast.horizon_periods}-{forecast.frequency === "D" ? "day" : forecast.frequency === "W" ? "week" : "month"} plan under {rec.policy_name} policy.
                </p>
              </div>
              <OrderScheduleTable schedule={rec.schedule} skuId={decoded} />
            </div>
          )}

          <DecompositionTabs datasetId={id} skuId={decoded} />
        </div>

        <div className="space-y-4">
          <RecommendationCard rec={rec} forecast={forecast} />
          {forecast.audit?.ensemble_weights && Object.keys(forecast.audit.ensemble_weights).length > 0 && (
            <EnsembleNarrative weights={forecast.audit.ensemble_weights} />
          )}
          {forecast.conformal_coverage && forecast.conformal_coverage.length > 0 && (
            <ConformalCoverageCard coverage={forecast.conformal_coverage} />
          )}
          <ScenarioSliders datasetId={id} skuId={decoded} base={rec} />
          <CalibrationCard datasetId={id} skuId={decoded} />

          {forecast.caveats.length > 0 && (
            <div className="space-y-1 rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-xs">
              <p className="font-medium text-yellow-700 dark:text-yellow-300">Watch-outs</p>
              <ul className="list-disc pl-4 text-foreground/80">
                {forecast.caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      <AuditFooter audit={forecast.audit} />
    </main>
  );
}
