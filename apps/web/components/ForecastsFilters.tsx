"use client";

import { Search, X } from "lucide-react";
import type { SkuStatus, SkuTableRow } from "@/lib/types";
import { STATUS_LABELS } from "@/components/StatusPill";

interface Props {
  rows: SkuTableRow[];
  query: string;
  onQuery: (s: string) => void;
  category: string | null;
  onCategory: (s: string | null) => void;
  abc: Set<string>;
  onAbc: (s: Set<string>) => void;
  xyz: Set<string>;
  onXyz: (s: Set<string>) => void;
  status: SkuStatus | null;
  onStatus: (s: SkuStatus | null) => void;
  needsActionOnly: boolean;
  onNeedsActionOnly: (b: boolean) => void;
  onClearAll: () => void;
  /** Right-side slot for export / extra buttons. */
  rightSlot?: React.ReactNode;
}

function toggleSet(s: Set<string>, v: string): Set<string> {
  const next = new Set(s);
  if (next.has(v)) next.delete(v);
  else next.add(v);
  return next;
}

export function ForecastsFilters(props: Props) {
  const categories = Array.from(new Set(props.rows.map((r) => r.category).filter(Boolean) as string[])).sort();

  const anyActive =
    props.query ||
    props.category ||
    props.abc.size > 0 ||
    props.xyz.size > 0 ||
    props.status ||
    props.needsActionOnly;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card/40 px-4 py-3">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <input
          type="text"
          value={props.query}
          onChange={(e) => props.onQuery(e.target.value)}
          placeholder="Search SKU / category / supplier"
          className="h-8 w-64 rounded-md border border-input bg-background py-1 pl-7 pr-2 text-xs outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      <select
        value={props.category ?? ""}
        onChange={(e) => props.onCategory(e.target.value || null)}
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
      >
        <option value="">All categories</option>
        {categories.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      <div className="inline-flex items-center gap-0.5 rounded-md border border-input bg-background p-0.5">
        <span className="px-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">ABC</span>
        {(["A", "B", "C"] as const).map((cls) => (
          <button
            key={cls}
            type="button"
            onClick={() => props.onAbc(toggleSet(props.abc, cls))}
            className={
              "rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors " +
              (props.abc.has(cls) ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")
            }
          >
            {cls}
          </button>
        ))}
      </div>

      <div className="inline-flex items-center gap-0.5 rounded-md border border-input bg-background p-0.5">
        <span className="px-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">XYZ</span>
        {(["X", "Y", "Z"] as const).map((cls) => (
          <button
            key={cls}
            type="button"
            onClick={() => props.onXyz(toggleSet(props.xyz, cls))}
            className={
              "rounded px-1.5 py-0.5 text-[11px] font-medium transition-colors " +
              (props.xyz.has(cls) ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")
            }
          >
            {cls}
          </button>
        ))}
      </div>

      <select
        value={props.status ?? ""}
        onChange={(e) => props.onStatus((e.target.value || null) as SkuStatus | null)}
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
      >
        <option value="">All statuses</option>
        {(Object.keys(STATUS_LABELS) as SkuStatus[]).map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
          </option>
        ))}
      </select>

      <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={props.needsActionOnly}
          onChange={(e) => props.onNeedsActionOnly(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-input"
        />
        Needs action only
      </label>

      {anyActive && (
        <button
          type="button"
          onClick={props.onClearAll}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground"
        >
          <X className="h-3 w-3" aria-hidden /> Clear filters
        </button>
      )}

      <div className="ml-auto flex items-center gap-2">{props.rightSlot}</div>
    </div>
  );
}
