import type { AggregateStats } from "@/lib/types";
import { cn } from "@/lib/utils";

const ABC = ["A", "B", "C"] as const;
const XYZ = ["X", "Y", "Z"] as const;

const CELL_HINT: Record<string, string> = {
  AX: "high revenue, stable — continuous review, tight reorder",
  AY: "high revenue, moderate variance — continuous review",
  AZ: "high revenue, high variance — careful safety stock",
  BX: "mid revenue, stable — periodic review",
  BY: "mid revenue, moderate variance — periodic review",
  BZ: "mid revenue, high variance — review weekly",
  CX: "low revenue, stable — long review cycle",
  CY: "low revenue, moderate variance — bundle reorders",
  CZ: "low revenue, high variance — review on demand or drop",
};

function intensity(count: number, max: number): string {
  if (max <= 0) return "bg-muted/40";
  const t = count / max;
  if (t < 0.05) return "bg-muted/30";
  if (t < 0.2) return "bg-primary/15";
  if (t < 0.4) return "bg-primary/30";
  if (t < 0.6) return "bg-primary/50";
  if (t < 0.8) return "bg-primary/65";
  return "bg-primary/80";
}

export function AbcXyzHeatmap({ stats }: { stats: AggregateStats }) {
  const heatmap = stats.abc_xyz_heatmap;
  const max = Math.max(0, ...Object.values(heatmap));

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h3 className="text-sm font-semibold">ABC × XYZ</h3>
          <p className="text-xs text-muted-foreground">Revenue importance × demand variability</p>
        </div>
        <p className="text-xs text-muted-foreground">{stats.n_skus.toLocaleString()} SKUs</p>
      </div>
      <div className="mt-3 grid grid-cols-[1.5rem_repeat(3,minmax(0,1fr))] gap-1">
        <div />
        {XYZ.map((x) => (
          <div key={x} className="text-center text-xs font-medium text-muted-foreground">
            {x}
          </div>
        ))}
        {ABC.map((a) => (
          <>
            <div key={`row-${a}`} className="flex items-center text-xs font-medium text-muted-foreground">
              {a}
            </div>
            {XYZ.map((x) => {
              const key = `${a}${x}`;
              const count = heatmap[key] ?? 0;
              return (
                <div
                  key={key}
                  title={`${key}: ${count} SKUs — ${CELL_HINT[key]}`}
                  className={cn(
                    "flex h-12 items-center justify-center rounded text-sm font-medium tabular-nums text-foreground",
                    intensity(count, max),
                  )}
                >
                  {count}
                </div>
              );
            })}
          </>
        ))}
      </div>
    </div>
  );
}
