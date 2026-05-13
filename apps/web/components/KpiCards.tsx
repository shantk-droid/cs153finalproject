import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { MethodologyDrawer } from "@/components/MethodologyDrawer";
import { Sparkline } from "@/components/Sparkline";
import type { AggregateStats } from "@/lib/types";
import { cn } from "@/lib/utils";

function formatCurrency(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

function Delta({ pct }: { pct: number | null | undefined }) {
  if (pct === null || pct === undefined || isNaN(pct)) return null;
  const sign = pct > 0.01 ? 1 : pct < -0.01 ? -1 : 0;
  const Icon = sign > 0 ? TrendingUp : sign < 0 ? TrendingDown : Minus;
  const color = sign > 0 ? "text-emerald-600" : sign < 0 ? "text-red-600" : "text-muted-foreground";
  return (
    <span className={cn("ml-1 inline-flex items-center text-[11px] font-medium", color)}>
      <Icon className="mr-0.5 h-3 w-3" />
      {pct > 0 ? "+" : ""}
      {(pct * 100).toFixed(1)}%
    </span>
  );
}

interface KpiCardProps {
  label: string;
  value: string;
  hint?: string;
  deltaPct?: number | null;
  sparkline?: number[] | null;
  metric?: string;
  contextValues?: Record<string, string | number | null>;
}

function Card({ label, value, hint, deltaPct, sparkline, metric, contextValues }: KpiCardProps) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="inline-flex items-center text-xs uppercase tracking-wide text-muted-foreground">
          {label}
          {metric && <MethodologyDrawer metric={metric} contextValues={contextValues} />}
        </p>
        {sparkline && sparkline.length > 1 && (
          <span className="text-primary">
            <Sparkline values={sparkline} width={56} height={18} />
          </span>
        )}
      </div>
      <p className="mt-1 flex items-baseline text-2xl font-semibold tabular-nums">
        {value}
        <Delta pct={deltaPct} />
      </p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function KpiCards({ stats }: { stats: AggregateStats }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Card
        label="SKUs"
        value={stats.n_skus.toLocaleString()}
        hint={`${stats.n_skus_low_history} low-history`}
        metric="abc_xyz"
      />
      <Card
        label="Annual revenue"
        value={formatCurrency(stats.total_revenue_annual)}
      />
      <Card
        label="Inventory value"
        value={formatCurrency(stats.total_inventory_value)}
        hint={stats.total_inventory_value === null ? "no on_hand data" : undefined}
        metric="cash_to_cash"
      />
      <Card
        label="Avg days of cover"
        value={stats.avg_days_of_cover === null ? "—" : `${stats.avg_days_of_cover}d`}
        hint={stats.avg_days_of_cover === null ? "no on_hand data" : undefined}
        metric="days_of_cover"
        contextValues={{
          "Avg DoC": stats.avg_days_of_cover === null ? null : `${stats.avg_days_of_cover}d`,
          "# SKUs": stats.n_skus,
        }}
      />
    </div>
  );
}
