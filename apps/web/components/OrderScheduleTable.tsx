"use client";

import { Download } from "lucide-react";
import { downloadCsv } from "@/lib/api-client";
import type { ScheduleEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTION_LABEL: Record<ScheduleEntry["action"], string> = {
  order: "ORDER",
  delivery: "DELIVERY",
  no_op: "—",
  stockout: "STOCKOUT",
};

const ACTION_STYLE: Record<ScheduleEntry["action"], string> = {
  order: "bg-primary/15 text-primary",
  delivery: "bg-green-500/15 text-green-700 dark:text-green-400",
  no_op: "bg-muted text-muted-foreground",
  stockout: "bg-destructive/15 text-destructive",
};

function shortenReason(e: ScheduleEntry): string {
  if (!e.reason) return "";
  const reviewMatch = e.reason.match(/review\s*@\s*t=(\d+)/i);
  const arriveMatch = e.reason.match(/arrives?\s+([\d-]+)/i);
  const parts: string[] = [];
  if (reviewMatch) parts.push(`Triggered at review wk ${reviewMatch[1]}`);
  if (arriveMatch) parts.push(`arrives ${arriveMatch[1].slice(5)}`);
  if (parts.length > 0) return parts.join(" · ");
  return e.reason.replace(/delivery of [\d.]+ units/i, "").trim();
}

export function OrderScheduleTable({
  schedule,
  skuId,
}: {
  schedule: ScheduleEntry[];
  skuId?: string;
}) {
  if (!schedule || schedule.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No schedule available. Schedule generation is enabled for (Q,R), (s,S), and base-stock policies.
      </p>
    );
  }

  const orders = schedule.filter((e) => e.action === "order");
  const totalQty = orders.reduce((s, e) => s + e.qty, 0);

  const exportCsv = () => {
    downloadCsv(
      `order-schedule-${skuId ?? "sku"}.csv`,
      schedule.map((e) => ({
        period: e.period_idx,
        date: e.date,
        action: e.action,
        qty: e.qty,
        expected_on_hand_after_demand: e.expected_on_hand_after_demand,
        expected_on_hand_after_delivery: e.expected_on_hand_after_delivery,
        expected_arrival: e.expected_arrival ?? "",
        reason: e.reason ?? "",
      })),
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <p className="text-sm">
          <span className="font-semibold">{orders.length}</span>
          <span className="text-muted-foreground"> order{orders.length === 1 ? "" : "s"} planned · </span>
          <span className="font-semibold tabular-nums">{Math.round(totalQty)}</span>
          <span className="text-muted-foreground"> total units</span>
        </p>
        <button
          type="button"
          onClick={exportCsv}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] hover:bg-muted"
        >
          <Download className="h-3 w-3" aria-hidden /> Export CSV
        </button>
      </div>
      <div className="overflow-auto rounded-md border">
        <table className="min-w-full text-xs">
          <thead className="bg-muted">
            <tr>
              <th className="border-b px-2 py-1.5 text-left font-medium">Date</th>
              <th className="border-b px-2 py-1.5 text-left font-medium">Action</th>
              <th className="border-b px-2 py-1.5 text-right font-medium">Qty</th>
              <th className="border-b px-2 py-1.5 text-right font-medium">On hand</th>
              <th className="border-b px-2 py-1.5 text-left font-medium">Notes</th>
            </tr>
          </thead>
          <tbody>
            {schedule.map((e) => (
              <tr key={e.period_idx} className={cn("border-b last:border-b-0", e.action === "no_op" && "opacity-60")}>
                <td className="whitespace-nowrap px-2 py-1.5 font-mono">{e.date}</td>
                <td className="px-2 py-1.5">
                  <span className={cn("rounded px-1.5 py-0.5 text-xs font-medium", ACTION_STYLE[e.action])}>
                    {ACTION_LABEL[e.action]}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {e.qty > 0 ? Math.round(e.qty) : "—"}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {Math.round(e.expected_on_hand_after_delivery)}
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">
                  {shortenReason(e)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
