import Link from "next/link";
import { notFound } from "next/navigation";
import { AbcXyzHeatmap } from "@/components/AbcXyzHeatmap";
import { HelpTooltip } from "@/components/HelpTooltip";
import { LlmInsightsPanel } from "@/components/LlmInsightsPanel";
import { JointReplenPanel } from "@/components/JointReplenPanel";
import { KpiCards } from "@/components/KpiCards";
import { SkuTable } from "@/components/SkuTable";
import { InsightsTile } from "@/components/InsightsTile";
import { WorkingCapitalTile } from "@/components/WorkingCapitalTile";
import { serverFetch } from "@/lib/api-server";
import { deriveForecastInsights, summarizePanel } from "@/lib/insights";
import type { AggregateStats, DataQualityReport, SkuTableRow } from "@/lib/types";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function OverviewPage({ params }: Props) {
  const { id } = await params;
  const [stats, rows, dq] = await Promise.all([
    serverFetch<AggregateStats>(`/datasets/${encodeURIComponent(id)}/aggregate_stats`),
    serverFetch<SkuTableRow[]>(
      `/datasets/${encodeURIComponent(id)}/skus?limit=2000&sort_by=revenue_annual&sort_dir=desc&include_history=true`,
    ),
    serverFetch<DataQualityReport>(`/datasets/${encodeURIComponent(id)}/quality`),
  ]);
  if (!stats || !rows) notFound();

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <header className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-widest text-muted-foreground">Overview</p>
          <h1 className="text-2xl font-semibold tracking-tight">
            Inventory snapshot
            <HelpTooltip text="A roll-up of every SKU in this panel: KPIs, ABC×XYZ mix, cross-SKU joint-replenishment opportunities, and the data-quality summary." />
          </h1>
        </div>
        <nav className="flex items-center gap-3 text-sm">
          <a
            href={`/api/datasets/${encodeURIComponent(id)}/export?fmt=xlsx`}
            className="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-accent"
          >
            Export XLSX
          </a>
        </nav>
      </header>

      <KpiCards stats={stats} />

      <LlmInsightsPanel
        datasetId={id}
        variant="panel"
        heuristics={deriveForecastInsights(rows)}
        summary={summarizePanel(rows)}
      />

      <section className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <SkuTable rows={rows} datasetId={id} />
          <AbcXyzHeatmap stats={stats} />
          <JointReplenPanel datasetId={id} />
        </div>
        <div className="flex flex-col gap-4">
          <InsightsTile datasetId={id} />
          <WorkingCapitalTile datasetId={id} />
          {dq && (
            <div className="rounded-lg border bg-card p-4">
              <h3 className="text-sm font-semibold">Data quality</h3>
              <p className="mt-1 flex items-baseline gap-2">
                <span className="text-3xl font-bold tabular-nums">
                  {dq.composite_score === null ? "—" : Math.round(dq.composite_score)}
                </span>
                <span className="text-xs text-muted-foreground">composite score</span>
              </p>
              <ul className="mt-2 space-y-1 text-xs">
                {dq.components.map((c) => (
                  <li key={c.name} className="flex items-center justify-between">
                    <span className="capitalize text-muted-foreground">{c.name.replace(/_/g, " ")}</span>
                    <span className="tabular-nums">
                      {c.score === null ? "—" : Math.round(c.score)}
                    </span>
                  </li>
                ))}
              </ul>
              <Link
                href={`/dashboard/${id}/quality`}
                className="mt-3 block text-xs underline-offset-4 hover:underline"
              >
                Full report →
              </Link>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
