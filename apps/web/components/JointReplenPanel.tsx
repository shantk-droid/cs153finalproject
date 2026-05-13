"use client";

import { useEffect, useState } from "react";

interface Group {
  supplier: string;
  group_id: string;
  cadence_days: number;
  n_members: number;
  members: { sku_id: string; individual_cycle_days: number }[];
  annual_orders_pooled: number;
  annual_orders_individual: number;
  annual_savings_usd: number;
  note: string | null;
}

export function JointReplenPanel({ datasetId }: { datasetId: string }) {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`/api/datasets/${encodeURIComponent(datasetId)}/joint_replenishment`);
        if (!r.ok) throw new Error(`API ${r.status}`);
        setGroups(await r.json());
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [datasetId]);

  if (error) return null;
  if (groups === null) {
    return (
      <div className="rounded-lg border bg-card p-4 text-xs text-muted-foreground">
        Computing joint-replenishment opportunities…
      </div>
    );
  }
  if (groups.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4 text-xs text-muted-foreground">
        No joint-replenishment groups found (need ≥2 SKUs from the same supplier with similar cycles).
      </div>
    );
  }

  const totalSavings = groups.reduce((s, g) => s + g.annual_savings_usd, 0);

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div>
        <h3 className="text-sm font-semibold">Joint replenishment</h3>
        <p className="text-xs text-muted-foreground">
          {groups.length} group{groups.length === 1 ? "" : "s"} · saves{" "}
          <span className="font-semibold tabular-nums">${totalSavings.toFixed(0)}</span>/yr in fixed order cost
        </p>
      </div>
      <ul className="space-y-1.5">
        {groups.slice(0, 5).map((g) => (
          <li key={g.group_id} className="rounded-md border p-2 text-xs">
            <div className="flex items-baseline justify-between">
              <span className="font-medium">{g.supplier}</span>
              <span className="text-muted-foreground">
                {g.n_members} SKUs · every {Math.round(g.cadence_days)}d · saves ${g.annual_savings_usd.toFixed(0)}/yr
              </span>
            </div>
            <p className="mt-1 truncate text-[11px] text-muted-foreground">
              {g.members.slice(0, 8).map((m) => m.sku_id).join(", ")}
              {g.members.length > 8 ? ` … +${g.members.length - 8} more` : ""}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
