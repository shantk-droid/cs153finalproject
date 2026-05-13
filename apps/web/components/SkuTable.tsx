"use client";

import { useMemo, useRef, useState } from "react";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import Link from "next/link";
import type { SkuTableRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { HelpTooltip } from "@/components/HelpTooltip";
import { Sparkline } from "@/components/Sparkline";

function HeaderWithTip({
  label,
  tip,
  align = "center",
}: {
  label: string;
  tip: string;
  align?: "center" | "end" | "start";
}) {
  return (
    <span className="inline-flex items-center">
      {label}
      <HelpTooltip text={tip} align={align} />
    </span>
  );
}

interface Props {
  rows: SkuTableRow[];
  datasetId: string;
}

// Grid column template — keep length + order in sync with `columns` below.
// Order: SKU, Last 12, Category, Supplier, ABC, XYZ, Last demand, On hand, Days of cover, CV, Annual rev, n obs.
// Supplier is the only flexible column so the table fills wide containers; everything else is a fixed pixel
// width so values in the same column line up perfectly across all rows.
const GRID_COLS =
  "108px 88px 116px minmax(160px,1fr) 64px 64px 108px 92px 124px 64px 132px 80px";

const ABC_COLOR: Record<string, string> = {
  A: "bg-primary/15 text-primary",
  B: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  C: "bg-muted text-muted-foreground",
};

const XYZ_COLOR: Record<string, string> = {
  X: "bg-green-500/15 text-green-700 dark:text-green-400",
  Y: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400",
  Z: "bg-destructive/15 text-destructive",
};

export function SkuTable({ rows, datasetId }: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "revenue_annual", desc: true }]);
  const [globalFilter, setGlobalFilter] = useState("");

  const columns = useMemo<ColumnDef<SkuTableRow>[]>(
    () => [
      {
        accessorKey: "sku_id",
        header: () => <HeaderWithTip label="SKU" tip="Unique SKU identifier. Click to open the per-SKU forecast + policy detail page." />,
        cell: ({ row }) => (
          <Link
            href={`/dashboard/${datasetId}/sku/${encodeURIComponent(row.original.sku_id)}`}
            className="font-mono text-xs underline-offset-4 hover:underline"
          >
            {row.original.sku_id}
          </Link>
        ),
      },
      {
        id: "trend",
        header: () => <HeaderWithTip label="Last 12" tip="Demand sparkline over the last 12 weeks. Visual cue for trend, seasonality, or intermittency." />,
        cell: ({ row }) => (
          <span className="text-primary inline-block">
            <Sparkline values={row.original.history ?? null} width={64} height={20} />
          </span>
        ),
      },
      {
        accessorKey: "category",
        header: () => <HeaderWithTip label="Category" tip="Product category from your panel. Useful for slicing by aisle / department." />,
        cell: (info) => info.getValue() ?? "—",
      },
      {
        accessorKey: "supplier",
        header: () => <HeaderWithTip label="Supplier" tip="Vendor that fulfills this SKU. Drives lead-time, OTIF, and joint-replenishment grouping." />,
        cell: (info) => info.getValue() ?? "—",
      },
      {
        accessorKey: "abc_class",
        header: () => <HeaderWithTip label="ABC" tip="Revenue tier. A = top 80% of revenue, B = next 15%, C = bottom 5%." />,
        cell: ({ row }) => (
          <span className={cn("rounded px-1.5 py-0.5 text-xs font-semibold", ABC_COLOR[row.original.abc_class])}>
            {row.original.abc_class}
          </span>
        ),
      },
      {
        accessorKey: "xyz_class",
        header: () => <HeaderWithTip label="XYZ" tip="Demand variability. X = stable (CV<0.5), Y = variable (0.5–1.0), Z = erratic (>1.0)." />,
        cell: ({ row }) => (
          <span className={cn("rounded px-1.5 py-0.5 text-xs font-semibold", XYZ_COLOR[row.original.xyz_class])}>
            {row.original.xyz_class}
          </span>
        ),
      },
      {
        accessorKey: "last_demand",
        header: () => <HeaderWithTip label="Last demand" tip="Demand observed in the most recent period (units). 0 means no sales that period — could be normal intermittency or a gap." />,
        cell: ({ row }) => row.original.last_demand.toFixed(0),
      },
      {
        accessorKey: "on_hand",
        header: () => <HeaderWithTip label="On hand" tip="Current inventory units physically in stock. Drives the days-of-cover calculation." />,
        cell: ({ row }) => row.original.on_hand?.toFixed(0) ?? "—",
      },
      {
        accessorKey: "days_of_cover",
        header: () => <HeaderWithTip label="Days of cover" tip="On-hand ÷ recent average daily demand. How many days the current stock will last at recent demand. Compare against lead time to gauge urgency." />,
        cell: ({ row }) => (row.original.days_of_cover === null ? "—" : `${row.original.days_of_cover}d`),
      },
      {
        accessorKey: "cv_demand",
        header: () => <HeaderWithTip label="CV" tip="Coefficient of variation = stdev(demand) / mean(demand). Higher = noisier; widens forecast intervals and safety stock." />,
        cell: ({ row }) => row.original.cv_demand.toFixed(2),
      },
      {
        accessorKey: "revenue_annual",
        header: () => <HeaderWithTip label="Annual rev" tip="Annualized revenue (mean demand × unit price × 365). Defines the ABC tier above." align="end" />,
        cell: ({ row }) => `$${row.original.revenue_annual.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      },
      {
        accessorKey: "n_obs",
        header: () => <HeaderWithTip label="n obs" tip="Number of demand observations in the panel for this SKU. Short history → wider intervals." align="end" />,
        cell: ({ row }) => row.original.n_obs,
      },
    ],
    [datasetId],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: (row, _id, filter) => {
      const f = String(filter).toLowerCase();
      return [row.original.sku_id, row.original.category ?? "", row.original.supplier ?? ""]
        .some((v) => String(v).toLowerCase().includes(f));
    },
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const { rows: tableRows } = table.getRowModel();
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => containerRef.current,
    estimateSize: () => 36,
    overscan: 8,
  });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <input
          type="search"
          placeholder="Search SKU, category, supplier…"
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="h-9 w-72 rounded-md border border-input bg-background px-3 text-sm"
        />
        <p className="text-xs text-muted-foreground">
          {tableRows.length.toLocaleString()} of {rows.length.toLocaleString()} SKUs
        </p>
      </div>

      <div
        ref={containerRef}
        className="relative h-[60vh] overflow-auto rounded-md border"
      >
        {/* CSS-grid layout (not <table>) so virtualized rows still share a single column template,
            and so the container can scroll horizontally when the natural width exceeds the viewport. */}
        <div role="table" className="min-w-max text-xs">
          <div
            role="rowgroup"
            className="sticky top-0 z-20 bg-card shadow-[0_1px_0_0_hsl(var(--border))]"
          >
            {table.getHeaderGroups().map((hg) => (
              <div
                role="row"
                key={hg.id}
                className="grid border-b"
                style={{ gridTemplateColumns: GRID_COLS }}
              >
                {hg.headers.map((header) => {
                  const sortDir = header.column.getIsSorted();
                  const sortLabel = sortDir === "asc" ? "ascending" : sortDir === "desc" ? "descending" : "none";
                  return (
                    <div
                      role="columnheader"
                      key={header.id}
                      aria-sort={sortDir === "asc" ? "ascending" : sortDir === "desc" ? "descending" : "none"}
                      className="flex items-center whitespace-nowrap px-3 py-2 text-left font-medium"
                    >
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className="inline-flex cursor-pointer items-center gap-1 rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        aria-label={`Sort, currently ${sortLabel}`}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sortDir === "asc" && <span aria-hidden>▲</span>}
                        {sortDir === "desc" && <span aria-hidden>▼</span>}
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          <div
            role="rowgroup"
            style={{ height: virtualizer.getTotalSize() }}
            className="relative"
          >
            {virtualizer.getVirtualItems().map((vrow) => {
              const row = tableRows[vrow.index];
              return (
                <div
                  role="row"
                  key={row.id}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    right: 0,
                    height: `${vrow.size}px`,
                    transform: `translateY(${vrow.start}px)`,
                    gridTemplateColumns: GRID_COLS,
                  }}
                  className="grid border-b hover:bg-accent/40"
                >
                  {row.getVisibleCells().map((cell) => (
                    <div
                      role="cell"
                      key={cell.id}
                      className="flex items-center overflow-hidden whitespace-nowrap px-3 text-left"
                    >
                      <span className="truncate">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </span>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
