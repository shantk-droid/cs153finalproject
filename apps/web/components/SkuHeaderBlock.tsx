"use client";

import { StatusPill } from "@/components/StatusPill";
import { derivePresentationStatus } from "@/lib/sku-status";
import type { Forecast, Recommendation } from "@/lib/types";

interface HistoryRow {
  date: string;
  demand: number;
}

interface Props {
  skuId: string;
  category: string | null;
  abc: "A" | "B" | "C";
  xyz: "X" | "Y" | "Z";
  history: HistoryRow[];
  forecast: Forecast;
  rec: Recommendation;
}

function nextOrderEntry(rec: Recommendation): { date: string; qty: number } | null {
  if (!rec.schedule || rec.schedule.length === 0) return null;
  const next = rec.schedule.find((e) => e.action === "order" && e.qty > 0);
  return next ? { date: next.date, qty: next.qty } : null;
}

export function SkuHeaderBlock({
  skuId,
  category,
  abc,
  xyz,
  history,
  forecast,
  rec,
}: Props) {
  const last7 = history.slice(-7).reduce((acc, r) => acc + (r.demand ?? 0), 0);
  const forecast7 = forecast.point.slice(0, 7).reduce((acc, v) => acc + v, 0);

  // Width of the 95% interval, summed over the same horizon.
  const lo = forecast.quantiles?.["0.025"]?.slice(0, 7) ?? [];
  const hi = forecast.quantiles?.["0.975"]?.slice(0, 7) ?? [];
  const intervalHalf =
    lo.length === hi.length && lo.length > 0
      ? Math.round(hi.reduce((a, b, i) => a + (b - lo[i]) / 2, 0))
      : null;

  const onHand = rec.parameters && typeof rec.parameters["on_hand_now"] === "number"
    ? Number(rec.parameters["on_hand_now"])
    : null;

  const status = derivePresentationStatus(rec);
  const reorderPoint = rec.reorder_point != null ? Math.round(rec.reorder_point) : null;
  const next = nextOrderEntry(rec);

  let actionLine: string;
  if (status === "order_now") {
    actionLine = `Order now — recommended ${Math.round(rec.recommended_order_qty)} units.`;
  } else if (status === "at_risk") {
    actionLine = `At risk — projected stockout within lead time × 1.5. Consider expediting.`;
  } else if (status === "watch") {
    actionLine = `Watch — fill rate below target. Hold for now; monitor next review.`;
  } else if (reorderPoint != null) {
    actionLine = `Healthy. No order needed today (reorder point ${reorderPoint}).`;
  } else {
    actionLine = `Healthy.`;
  }

  return (
    <section className="space-y-3 rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="font-mono text-2xl font-semibold tracking-tight">{skuId}</h1>
        {category && <span className="text-sm text-muted-foreground">· {category}</span>}
        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-semibold text-primary">
          {abc}-{xyz}
        </span>
        <StatusPill status={status} />
      </div>

      <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Last 7 days" value={`${Math.round(last7)} u`} />
        <Stat
          label="Forecast next 7 days"
          value={
            intervalHalf != null
              ? `${Math.round(forecast7)} u (±${intervalHalf} at 95%)`
              : `${Math.round(forecast7)} u`
          }
        />
        {reorderPoint != null && <Stat label="Reorder point (s)" value={`${reorderPoint} u`} />}
        {next ? (
          <Stat label="Next planned order" value={`${next.date} · ${Math.round(next.qty)} u`} />
        ) : (
          <Stat label="Next planned order" value="None in horizon" />
        )}
      </div>

      <p className="text-sm text-foreground/85">{actionLine}</p>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-base font-semibold tabular-nums">{value}</p>
    </div>
  );
}
