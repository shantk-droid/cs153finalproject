import { HelpTooltip } from "@/components/HelpTooltip";
import type { Forecast, Recommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLICY_HINT: Record<string, string> = {
  EOQ: "Stable demand, deterministic lead time. Q* minimizes holding + ordering cost.",
  "(Q,R)": "Continuous review. Order Q every time inventory drops to R.",
  "(s,S)": "Periodic review. When inventory ≤ s, order up to S.",
  newsvendor: "Single-period perishable. Q* solves Cu / (Cu + Co).",
  "base-stock": "Order up to S every period.",
};

const PARAM_LABEL: Record<string, string> = {
  s: "s — reorder point",
  S: "S — order-up-to level",
  Q: "Q — order quantity",
  R: "R — reorder point",
  review_period_periods: "Review period (periods)",
  expected_orders_per_year: "Expected orders / year",
  underage_cost: "Underage cost (per unit short)",
  overage_cost: "Overage cost (per unit excess)",
};

const PARAM_HELP: Record<string, string> = {
  s: "Reorder when on-hand drops to or below this. Formula: s = E[demand over LT] + zα·σ_LT.",
  S: "Order up to this level on a triggered review. Formula: S = s + EOQ.",
  Q: "Fixed order quantity each time you order.",
  R: "Reorder when on-hand reaches R.",
  review_period_periods:
    "How often inventory is reviewed (in forecast periods). For weekly data, 2 = every 2 weeks.",
};

function fmt(n: number, digits = 1): string {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(digits)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(digits)}k`;
  return n.toFixed(digits);
}

function reviewLabel(periods: number, frequency: "D" | "W" | "M" | undefined): string {
  if (!frequency) return `Every ${Math.round(periods)} periods`;
  const unit = frequency === "D" ? "day" : frequency === "W" ? "week" : "month";
  const n = Math.round(periods);
  if (n === 1) return `Every ${unit}`;
  return `Every ${n} ${unit}s`;
}

export function RecommendationCard({
  rec,
  forecast,
}: {
  rec: Recommendation;
  forecast?: Forecast;
}) {
  const params = Object.entries(rec.parameters).filter(([k]) => k !== "on_hand_now");

  return (
    <div className="space-y-4 rounded-lg border bg-card p-5">
      <header className="flex items-baseline justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Policy</p>
          <h3 className="text-xl font-semibold">{rec.policy_name}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{POLICY_HINT[rec.policy_name]}</p>
        </div>
        <div className="text-right">
          <span className="rounded bg-primary/15 px-1.5 py-0.5 text-xs font-semibold text-primary">
            {rec.abc_class}
            {rec.xyz_class}
          </span>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3">
        <Tile
          label="Order qty"
          value={fmt(rec.recommended_order_qty, 0)}
          help="Recommended quantity to place on the next order."
        />
        {rec.reorder_point !== null && (
          <Tile
            label="Reorder point"
            value={fmt(rec.reorder_point, 0)}
            help={PARAM_HELP.s}
          />
        )}
        <Tile
          label="Safety stock"
          value={fmt(rec.safety_stock, 0)}
          help="Buffer above expected lead-time demand to hit the chosen service level."
        />
        <Tile
          label="Stockout risk"
          value={`${(rec.expected_stockout_prob * 100).toFixed(1)}%`}
          help="Probability of stockout per replenishment cycle (lead time + review). High annualized rates may still mean modest per-cycle risk."
          valueClass={rec.expected_stockout_prob > 0.1 ? "text-destructive" : undefined}
        />
        <Tile
          label="Fill rate"
          value={`${(rec.expected_fill_rate * 100).toFixed(1)}%`}
          help="Expected fraction of demand filled from stock. Below 95% target → flagged for service-level tuning."
          valueClass={rec.expected_fill_rate < 0.95 ? "text-destructive" : undefined}
        />
        <Tile
          label="Annual cost"
          value={`$${fmt(rec.expected_total_cost_annual, 0)}`}
          help="Holding + ordering + expected stockout cost, annualized from the policy simulation."
        />
      </div>

      {params.length > 0 && (
        <details className="rounded-md border bg-muted/30">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Parameters</summary>
          <table className="w-full text-xs">
            <tbody>
              {params.map(([k, v]) => {
                const label = PARAM_LABEL[k] ?? k;
                let display: string;
                if (k === "review_period_periods" && typeof v === "number") {
                  display = reviewLabel(v, forecast?.frequency);
                } else if (typeof v === "number") {
                  display = (k === "s" || k === "S" || k === "Q" || k === "R") ? Math.round(v).toString() : v.toFixed(2);
                } else {
                  display = String(v);
                }
                return (
                  <tr key={k} className="border-t">
                    <td className="px-3 py-1.5 text-muted-foreground">
                      {label}
                      {PARAM_HELP[k] && <HelpTooltip text={PARAM_HELP[k]} />}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{display}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </details>
      )}

      {rec.caveats.length > 0 && (
        <div className="space-y-1 rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-xs">
          <p className="font-medium text-yellow-700 dark:text-yellow-300">Watch-outs</p>
          <ul className="list-disc pl-4 text-foreground/80">
            {rec.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Tile({
  label,
  value,
  help,
  valueClass,
}: {
  label: string;
  value: string;
  help?: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-xs text-muted-foreground">
        {label}
        {help && <HelpTooltip text={help} />}
      </p>
      <p className={cn("text-2xl font-semibold tabular-nums", valueClass)}>{value}</p>
    </div>
  );
}
