"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronUp, Download } from "lucide-react";
import { ForecastsFilters } from "@/components/ForecastsFilters";
import { ForecastsHeaderTiles } from "@/components/ForecastsHeaderTiles";
import { HelpTooltip } from "@/components/HelpTooltip";
import { LlmInsightsPanel } from "@/components/LlmInsightsPanel";
import { Sparkline } from "@/components/Sparkline";
import { StatusPill } from "@/components/StatusPill";
import { downloadCsv } from "@/lib/api-client";
import { deriveForecastInsights, summarizePanel } from "@/lib/insights";
import type { SkuStatus, SkuTableRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type SortKey = "sku_id" | "revenue_annual" | "cv_demand" | "days_of_cover" | "last_demand" | "status";
const STATUS_ORDER: Record<SkuStatus, number> = { order_now: 0, at_risk: 1, watch: 2, healthy: 3 };

function ClassBadge({ value }: { value: "A" | "B" | "C" | "X" | "Y" | "Z" }) {
  const colorMap: Record<string, string> = {
    A: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
    B: "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
    C: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    X: "bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300",
    Y: "bg-purple-100 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300",
    Z: "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300",
  };
  return (
    <span
      className={cn(
        "inline-flex h-5 w-5 items-center justify-center rounded text-xs font-medium",
        colorMap[value],
      )}
    >
      {value}
    </span>
  );
}

function docColor(doc: number | null): string {
  if (doc === null) return "";
  if (doc < 7) return "text-rose-700 dark:text-rose-300";
  if (doc < 14) return "text-amber-700 dark:text-amber-300";
  return "";
}

export function ForecastsTable({ rows, datasetId }: { rows: SkuTableRow[]; datasetId: string }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [abc, setAbc] = useState<Set<string>>(new Set(["A", "B"]));
  const [xyz, setXyz] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<SkuStatus | null>(null);
  const [needsActionOnly, setNeedsActionOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("days_of_cover");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let xs = rows;
    if (q) {
      xs = xs.filter((r) =>
        [r.sku_id, r.category, r.supplier].filter(Boolean).some((s) => s!.toLowerCase().includes(q)),
      );
    }
    if (category) xs = xs.filter((r) => r.category === category);
    if (abc.size > 0) xs = xs.filter((r) => abc.has(r.abc_class));
    if (xyz.size > 0) xs = xs.filter((r) => xyz.has(r.xyz_class));
    if (status) xs = xs.filter((r) => r.status === status);
    if (needsActionOnly) xs = xs.filter((r) => r.status === "order_now" || r.status === "at_risk");

    xs = [...xs].sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      if (sortKey === "status") {
        av = STATUS_ORDER[a.status];
        bv = STATUS_ORDER[b.status];
      } else if (sortKey === "days_of_cover") {
        av = a.days_of_cover ?? Number.POSITIVE_INFINITY;
        bv = b.days_of_cover ?? Number.POSITIVE_INFINITY;
      } else {
        av = (a[sortKey] ?? 0) as number | string;
        bv = (b[sortKey] ?? 0) as number | string;
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return xs;
  }, [rows, query, category, abc, xyz, status, needsActionOnly, sortKey, sortDir]);

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(k);
      // Sensible per-column default direction
      setSortDir(
        k === "sku_id" || k === "days_of_cover" || k === "status" ? "asc" : "desc",
      );
    }
  }

  function exportCsv() {
    downloadCsv(
      `forecasts-${datasetId}.csv`,
      filtered.map((r) => ({
        sku_id: r.sku_id,
        status: r.status,
        category: r.category ?? "",
        supplier: r.supplier ?? "",
        abc_class: r.abc_class,
        xyz_class: r.xyz_class,
        on_hand: r.on_hand ?? "",
        days_of_cover: r.days_of_cover ?? "",
        last_demand: r.last_demand,
        cv_demand: r.cv_demand,
        revenue_annual: r.revenue_annual,
        lead_time_days: r.lead_time_days ?? "",
      })),
    );
  }

  function clearAll() {
    setQuery("");
    setCategory(null);
    setAbc(new Set());
    setXyz(new Set());
    setStatus(null);
    setNeedsActionOnly(false);
  }

  function SortHeader({
    id,
    label,
    tooltip,
    align = "left",
  }: {
    id: SortKey;
    label: string;
    tooltip?: string;
    align?: "left" | "right" | "center";
  }) {
    const active = sortKey === id;
    return (
      <th
        className={cn(
          "px-3 py-2 text-xs uppercase tracking-wider text-muted-foreground",
          align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left",
        )}
      >
        <button
          type="button"
          onClick={() => toggleSort(id)}
          className="inline-flex items-center gap-1 hover:text-foreground"
        >
          {label}
          {active && (sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
        </button>
        {tooltip && <HelpTooltip text={tooltip} />}
      </th>
    );
  }

  const insights = deriveForecastInsights(filtered);
  const empty = filtered.length === 0;

  return (
    <div className="space-y-3">
      <ForecastsHeaderTiles
        rows={rows}
        activeStatus={status}
        onSelectStatus={(s) => setStatus(s)}
      />

      <div className="overflow-hidden rounded-lg border bg-card">
        <ForecastsFilters
          rows={rows}
          query={query}
          onQuery={setQuery}
          category={category}
          onCategory={setCategory}
          abc={abc}
          onAbc={setAbc}
          xyz={xyz}
          onXyz={setXyz}
          status={status}
          onStatus={setStatus}
          needsActionOnly={needsActionOnly}
          onNeedsActionOnly={setNeedsActionOnly}
          onClearAll={clearAll}
          rightSlot={
            <>
              <span className="text-xs text-muted-foreground">
                {filtered.length.toLocaleString()} of {rows.length.toLocaleString()} SKUs
              </span>
              <button
                type="button"
                onClick={exportCsv}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-[11px] hover:bg-muted"
              >
                <Download className="h-3 w-3" aria-hidden /> Export CSV
              </button>
            </>
          }
        />

        <div className="max-h-[640px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur">
              <tr className="border-b">
                <SortHeader id="status" label="Status" align="left" />
                <SortHeader id="sku_id" label="SKU" />
                <th className="hidden px-3 py-2 text-left text-xs uppercase tracking-wider text-muted-foreground sm:table-cell">
                  12-wk trend
                  <HelpTooltip text="Demand over the last 12 weeks. Green dot = max, red dot = min." />
                </th>
                <th className="hidden px-3 py-2 text-left text-xs uppercase tracking-wider text-muted-foreground md:table-cell">
                  Category
                </th>
                <SortHeader id="last_demand" label="Yesterday" align="right" />
                <SortHeader id="revenue_annual" label="Annual rev" align="right" />
                <th className="hidden px-3 py-2 text-center text-xs uppercase tracking-wider text-muted-foreground md:table-cell">
                  ABC class
                  <HelpTooltip text="A = top 80% of revenue, B = next 15%, C = bottom 5%." />
                </th>
                <th className="hidden px-3 py-2 text-center text-xs uppercase tracking-wider text-muted-foreground md:table-cell">
                  XYZ class
                  <HelpTooltip text="X = stable demand (CV<0.5), Y = variable (0.5–1.0), Z = erratic (>1.0)." />
                </th>
                <th className="hidden px-3 py-2 text-right text-xs uppercase tracking-wider text-muted-foreground lg:table-cell">
                  <button
                    type="button"
                    onClick={() => toggleSort("cv_demand")}
                    className="inline-flex items-center gap-1 hover:text-foreground"
                  >
                    Demand CV
                    {sortKey === "cv_demand" &&
                      (sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
                  </button>
                  <HelpTooltip text="Coefficient of variation of weekly demand. Higher = noisier." />
                </th>
                <SortHeader
                  id="days_of_cover"
                  label="Days cover"
                  align="right"
                  tooltip="On-hand ÷ recent average daily demand. How many days the current stock will last at recent demand. Compare against lead time to gauge urgency. Color: red <7d, amber <14d."
                />
                <th className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted-foreground">
                  On hand
                  <HelpTooltip
                    text="Current inventory in stock. Values like '146 u' mean 146 units (the 'u' suffix is the count of physical units on the shelf). '—' means unreported."
                    align="end"
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 500).map((r) => {
                const yesterdayClass =
                  r.last_demand === 0
                    ? "text-muted-foreground/60"
                    : "";
                const lastLabel =
                  r.last_demand === 0 ? "No sales yesterday" : `Yesterday: ${r.last_demand.toFixed(0)}`;
                return (
                  <tr key={r.sku_id} className="border-t hover:bg-muted/30">
                    <td className="px-3 py-1.5">
                      <StatusPill status={r.status} size="sm" />
                    </td>
                    <td className="px-3 py-1.5">
                      <Link
                        href={`/dashboard/${datasetId}/sku/${encodeURIComponent(r.sku_id)}`}
                        className="font-mono text-xs font-medium hover:underline"
                      >
                        {r.sku_id}
                      </Link>
                    </td>
                    <td className="hidden px-3 py-1.5 text-primary sm:table-cell">
                      <Sparkline values={r.history ?? null} />
                    </td>
                    <td className="hidden px-3 py-1.5 text-xs text-muted-foreground md:table-cell">
                      {r.category ?? "—"}
                    </td>
                    <td
                      className={cn("px-3 py-1.5 text-right tabular-nums", yesterdayClass)}
                      aria-label={lastLabel}
                      title={lastLabel}
                    >
                      {r.last_demand.toFixed(0)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      ${(r.revenue_annual / 1000).toFixed(1)}k
                    </td>
                    <td className="hidden px-3 py-1.5 text-center md:table-cell">
                      <ClassBadge value={r.abc_class} />
                    </td>
                    <td className="hidden px-3 py-1.5 text-center md:table-cell">
                      <ClassBadge value={r.xyz_class} />
                    </td>
                    <td className="hidden px-3 py-1.5 text-right tabular-nums lg:table-cell">
                      {r.cv_demand.toFixed(2)}
                    </td>
                    <td className={cn("px-3 py-1.5 text-right tabular-nums", docColor(r.days_of_cover))}>
                      {r.days_of_cover === null ? "—" : `${r.days_of_cover.toFixed(0)}d`}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">
                      {r.on_hand === null ? "—" : `${r.on_hand.toFixed(0)} u`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {empty && (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
            <p className="text-sm text-muted-foreground">No SKUs match these filters.</p>
            <button
              type="button"
              onClick={clearAll}
              className="text-xs font-medium text-primary hover:underline"
            >
              Clear filters
            </button>
          </div>
        )}
      </div>

      {filtered.length > 500 && (
        <p className="text-center text-xs text-muted-foreground">
          Showing first 500 — refine filters to see more
        </p>
      )}

      <LlmInsightsPanel
        datasetId={datasetId}
        variant="panel"
        heuristics={insights}
        summary={summarizePanel(filtered)}
      />
    </div>
  );
}
