"use client";

import { useEffect, useState } from "react";
import {
  Loader2, PackageCheck, Plane, RefreshCw,
} from "lucide-react";
import { HelpTooltip } from "@/components/HelpTooltip";
import type { ReorderQueueItem } from "@/lib/types";

interface QueueResp {
  items: ReorderQueueItem[];
  generated_at: string;
}

export function ReorderPageClient({ datasetId }: { datasetId: string }) {
  const [queue, setQueue] = useState<ReorderQueueItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`/api/datasets/${datasetId}/reorder/queue?limit=200`);
      if (!r.ok) throw new Error(`API ${r.status}`);
      const q = (await r.json()) as QueueResp;
      setQueue(q.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId]);

  return (
    <div className="space-y-6">
      <section className="rounded-lg border bg-card">
        <header className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">Reorder queue (top 200)</h2>
            <p className="text-xs text-muted-foreground">
              Score = stockout-prob × revenue-at-risk
            </p>
          </div>
          <button
            type="button"
            onClick={loadAll}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </header>
        {error && (
          <div className="border-b bg-red-50 px-4 py-2 text-xs text-red-700 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </div>
        )}
        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : queue && queue.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">
                    SKU
                    <HelpTooltip text="SKU identifier. Tagged 'expedite' if the projected stockout date sits inside the lead time. Tagged 'joint' if the supplier reaches MOQ by bundling co-supplied SKUs into one PO." />
                  </th>
                  <th className="px-3 py-2 text-left">
                    Supplier
                    <HelpTooltip text="Vendor that fulfills this SKU. Lead-time, MOQ, and OTIF come from this supplier's scorecard." />
                  </th>
                  <th className="px-3 py-2 text-right">
                    On hand
                    <HelpTooltip text="Current inventory units physically in stock right now." />
                  </th>
                  <th className="px-3 py-2 text-right">
                    ROP
                    <HelpTooltip text="Reorder point (s). When on-hand drops to this level, it's time to place a new order. ROP = expected lead-time demand + safety stock." />
                  </th>
                  <th className="px-3 py-2 text-right">
                    Recommend
                    <HelpTooltip text="Recommended order quantity, rounded up to MOQ and the case-pack multiple. The /N suffix shows the rounding step (case-pack)." />
                  </th>
                  <th className="px-3 py-2 text-right">
                    Stockout %
                    <HelpTooltip text="Probability of running out before the next order arrives, computed from the demand forecast distribution and lead-time variability." />
                  </th>
                  <th className="px-3 py-2 text-right">
                    $ at risk
                    <HelpTooltip text="Expected lost-sale dollars if you do nothing = stockout-prob × revenue exposed during the lead time. The queue is sorted by this score." />
                  </th>
                  <th className="px-3 py-2 text-left">
                    Stockout date
                    <HelpTooltip text="Estimated date you run out at the current pace, assuming no replenishment. Inside lead time → expedite flag fires on the SKU." />
                  </th>
                </tr>
              </thead>
              <tbody>
                {queue.map((it) => (
                  <tr key={it.sku_id} className="border-t hover:bg-muted/30">
                    <td className="px-3 py-2 font-mono text-xs">
                      {it.sku_id}
                      {it.expedite_flag && (
                        <span className="ml-1 inline-flex items-center gap-0.5 rounded bg-amber-100 px-1 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                          <Plane className="h-2.5 w-2.5" />
                          expedite
                        </span>
                      )}
                      {it.joint_replen_group && (
                        <span className="ml-1 inline-flex items-center gap-0.5 rounded bg-violet-100 px-1 py-0.5 text-[10px] font-medium text-violet-700 dark:bg-violet-950/40 dark:text-violet-300">
                          joint
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {it.supplier_name ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {it.on_hand === null ? "—" : it.on_hand.toFixed(0)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {it.reorder_point === null ? "—" : it.reorder_point.toFixed(0)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {it.recommended_qty.toFixed(0)}
                      {it.case_pack && it.case_pack > 1 && (
                        <span className="ml-1 text-[10px] text-muted-foreground">
                          /{it.case_pack}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {(it.stockout_prob * 100).toFixed(0)}%
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      ${(it.revenue_at_risk / 1000).toFixed(1)}k
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {it.projected_stockout_date ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
            <PackageCheck className="h-6 w-6" />
            <p className="text-sm">No SKUs need ordering right now.</p>
          </div>
        )}
      </section>
    </div>
  );
}
