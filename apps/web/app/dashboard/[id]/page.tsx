import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { InsightsPanel } from "@/components/InsightsPanel";
import { StatusPill } from "@/components/StatusPill";
import { serverFetch } from "@/lib/api-server";
import { deriveForecastInsights } from "@/lib/insights";
import type { DataQualityReport, SkuTableRow } from "@/lib/types";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function DashboardLanding({ params }: Props) {
  const { id } = await params;
  const [rows, dq] = await Promise.all([
    serverFetch<SkuTableRow[]>(
      `/datasets/${encodeURIComponent(id)}/skus?limit=2000&sort_by=days_of_cover&sort_dir=asc&include_history=false`,
    ),
    serverFetch<DataQualityReport>(`/datasets/${encodeURIComponent(id)}/quality`),
  ]);
  if (!rows) notFound();

  const orderNow = rows.filter((r) => r.status === "order_now").slice(0, 8);
  const atRisk = rows.filter((r) => r.status === "at_risk").slice(0, 8);
  const aClass = rows.filter((r) => r.abc_class === "A");
  const aHealthy = aClass.filter((r) => r.status === "healthy").length;
  const insights = deriveForecastInsights(rows);

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <header className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-widest text-muted-foreground">Dashboard</p>
          <h1 className="text-2xl font-semibold tracking-tight">Action queue</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            What needs your attention today. Reorder queue, stockout risks, and health snapshot.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href={`/dashboard/${id}/forecasts`}
            className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent"
          >
            All SKUs <ArrowRight className="h-3.5 w-3.5" />
          </Link>
          <Link
            href={`/dashboard/${id}/overview`}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-95"
          >
            Overview <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Need ordering" value={rows.filter((r) => r.status === "order_now").length.toLocaleString()} tone="warn" />
        <Stat label="Stockout risk" value={rows.filter((r) => r.status === "at_risk").length.toLocaleString()} tone="warn" />
        <Stat label="Healthy A-class" value={`${aHealthy}/${aClass.length}`} tone="good" />
        <Stat
          label="Data quality"
          value={dq?.composite_score == null ? "—" : Math.round(dq.composite_score).toString()}
          tone={dq?.composite_score == null ? "neutral" : dq.composite_score >= 80 ? "good" : "warn"}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border bg-card">
          <header className="flex items-center justify-between border-b px-4 py-2.5">
            <h2 className="text-sm font-semibold">This week's orders</h2>
            <Link
              href={`/dashboard/${id}/forecasts?status=order_now`}
              className="text-[11px] text-primary hover:underline"
            >
              See all →
            </Link>
          </header>
          <RowsList rows={orderNow} datasetId={id} emptyHint="No SKUs need ordering this week." />
        </div>

        <div className="rounded-lg border bg-card">
          <header className="flex items-center justify-between border-b px-4 py-2.5">
            <h2 className="text-sm font-semibold">Stockout risk in 4 weeks</h2>
            <Link
              href={`/dashboard/${id}/forecasts?status=at_risk`}
              className="text-[11px] text-primary hover:underline"
            >
              See all →
            </Link>
          </header>
          <RowsList rows={atRisk} datasetId={id} emptyHint="No SKUs at imminent stockout risk." />
        </div>
      </section>

      <InsightsPanel insights={insights} />
    </main>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "good" | "warn" | "neutral";
}) {
  const color =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "warn"
      ? "text-amber-600 dark:text-amber-400"
      : "text-foreground";
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
    </div>
  );
}

function RowsList({
  rows,
  datasetId,
  emptyHint,
}: {
  rows: SkuTableRow[];
  datasetId: string;
  emptyHint: string;
}) {
  if (rows.length === 0) {
    return <p className="px-4 py-6 text-center text-sm text-muted-foreground">{emptyHint}</p>;
  }
  return (
    <ul className="divide-y">
      {rows.map((r) => (
        <li
          key={r.sku_id}
          className="grid grid-cols-[auto_minmax(110px,140px)_1fr_64px_56px] items-center gap-3 px-4 py-2.5 text-xs hover:bg-muted/30"
        >
          <StatusPill status={r.status} size="sm" />
          <Link
            href={`/dashboard/${datasetId}/sku/${encodeURIComponent(r.sku_id)}`}
            className="truncate font-mono font-medium hover:underline"
          >
            {r.sku_id}
          </Link>
          <span className="truncate text-muted-foreground">{r.category ?? "—"}</span>
          <span className="text-right tabular-nums text-muted-foreground" title="On hand">
            {r.on_hand == null ? "—" : `${r.on_hand.toFixed(0)} u`}
          </span>
          <span className="text-right tabular-nums text-muted-foreground" title="Days of cover">
            {r.days_of_cover == null ? "—" : `${r.days_of_cover.toFixed(0)}d`}
          </span>
        </li>
      ))}
    </ul>
  );
}
