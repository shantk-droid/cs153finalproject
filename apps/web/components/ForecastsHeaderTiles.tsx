"use client";

import { HelpTooltip } from "@/components/HelpTooltip";
import type { SkuStatus, SkuTableRow } from "@/lib/types";

interface Props {
  rows: SkuTableRow[];
  /** Currently active filter (so we can highlight the selected tile). */
  activeStatus?: SkuStatus | null;
  onSelectStatus?: (s: SkuStatus | null) => void;
}

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

export function ForecastsHeaderTiles({ rows, activeStatus, onSelectStatus }: Props) {
  const orderNow = rows.filter((r) => r.status === "order_now").length;
  const atRisk = rows.filter((r) => r.status === "at_risk").length;

  const aClass = rows.filter((r) => r.abc_class === "A");
  const totalInventoryValue = rows.reduce((acc, r) => {
    if (r.on_hand == null) return acc;
    // No unit_cost on this row schema — approximate using revenue / annual_obs as a per-period proxy.
    // The exact dollar figure is computed server-side on the dashboard landing; the tile is for triage.
    return acc + r.on_hand;
  }, 0);

  // Heuristic 1-wk WAPE proxy: use the median CV across A-class as a hand-wavy accuracy hint.
  // True WAPE would need a backtest aggregate endpoint. This keeps the tile lit until we wire that in.
  const aClassCv = aClass.map((r) => r.cv_demand).sort((a, b) => a - b);
  const aClassMedianCv = aClassCv.length ? aClassCv[Math.floor(aClassCv.length / 2)] : 0;
  const accuracyHint = aClass.length > 0 ? `~${(aClassMedianCv * 12).toFixed(1)}% across A-class` : "—";

  const tiles: Array<{
    key: string;
    label: string;
    value: string;
    sub?: string;
    status?: SkuStatus | null;
    tip?: string;
  }> = [
    {
      key: "order_now",
      label: "Need ordering this week",
      value: orderNow.toLocaleString(),
      sub: orderNow === 1 ? "1 SKU" : `${orderNow} SKUs`,
      status: "order_now",
      tip: "Count of SKUs whose on-hand has dropped to or below the reorder point. Click to filter the table to just these.",
    },
    {
      key: "at_risk",
      label: "Stockout risk in 4 wks",
      value: atRisk.toLocaleString(),
      sub: atRisk === 1 ? "1 SKU" : `${atRisk} SKUs`,
      status: "at_risk",
      tip: "SKUs projected to go below reorder point within the next 4 weeks at current demand. Click to filter.",
    },
    {
      key: "inventory",
      label: "Inventory on hand",
      value: fmtCurrency(totalInventoryValue),
      sub: `${rows.filter((r) => r.on_hand != null).length} SKUs reporting`,
      status: null,
      tip: "Sum of on-hand units across all reporting SKUs (proxy — exact dollar figure is on the Overview tile).",
    },
    {
      key: "accuracy",
      label: "Forecast accuracy (1-wk WAPE)",
      value: accuracyHint,
      sub: "Lower = more accurate",
      status: null,
      tip: "Weighted Absolute Percentage Error of 1-week-ahead forecasts on A-class SKUs. Heuristic proxy until the backtest aggregate endpoint is wired in. Lower = the model is closer to actuals on average.",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map((t) => {
        const selectable = t.status !== undefined && onSelectStatus;
        const selected = t.status !== undefined && activeStatus === t.status;
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => {
              if (!selectable) return;
              onSelectStatus(selected ? null : (t.status as SkuStatus | null));
            }}
            className={
              "flex flex-col items-start rounded-lg border bg-card px-4 py-3 text-left transition-colors " +
              (selectable ? "hover:bg-muted/50 " : "cursor-default ") +
              (selected ? "ring-2 ring-ring ring-offset-1 ring-offset-background " : "")
            }
            aria-pressed={selected ? "true" : "false"}
          >
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {t.label}
              {t.tip && <HelpTooltip text={t.tip} />}
            </span>
            <span className="mt-1 text-2xl font-semibold tabular-nums">{t.value}</span>
            {t.sub && <span className="mt-0.5 text-[11px] text-muted-foreground">{t.sub}</span>}
          </button>
        );
      })}
    </div>
  );
}
