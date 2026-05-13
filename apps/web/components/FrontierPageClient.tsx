"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { HelpTooltip } from "@/components/HelpTooltip";
import { listSkus } from "@/lib/api-client";
import type { FrontierResult, SkuTableRow } from "@/lib/types";

export function FrontierPageClient({ datasetId }: { datasetId: string }) {
  const [skus, setSkus] = useState<SkuTableRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<FrontierResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [sl, setSl] = useState<number>(0.95);

  useEffect(() => {
    listSkus(datasetId, { limit: 1000, sort_by: "revenue_annual", sort_dir: "desc" })
      .then((rs) => {
        setSkus(rs);
        if (rs.length > 0) setSelected(rs[0].sku_id);
      });
  }, [datasetId]);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    fetch(`/api/datasets/${datasetId}/skus/${encodeURIComponent(selected)}/frontier`)
      .then((r) => r.json() as Promise<FrontierResult>)
      .then(setResult)
      .finally(() => setLoading(false));
  }, [selected, datasetId]);

  const chosen = useMemo(() => {
    if (!result) return null;
    let best = result.points[0];
    let bestDist = Math.abs(best.service_level - sl);
    for (const p of result.points) {
      const d = Math.abs(p.service_level - sl);
      if (d < bestDist) {
        best = p;
        bestDist = d;
      }
    }
    return best;
  }, [result, sl]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-foreground">SKU:</label>
        <select
          value={selected ?? ""}
          onChange={(e) => setSelected(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {skus?.slice(0, 200).map((s) => (
            <option
              key={s.sku_id}
              value={s.sku_id}
              className="bg-background text-foreground"
            >
              {s.sku_id} — {s.category ?? ""} — ${(s.revenue_annual / 1000).toFixed(1)}k/yr
            </option>
          ))}
        </select>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
      </div>

      {result && (
        <>
          <FrontierChart result={result} chosen={chosen} sl={sl} setSl={setSl} />
          <NewsvendorPanel result={result} />
        </>
      )}
    </div>
  );
}

function FrontierChart({
  result,
  chosen,
  sl,
  setSl,
}: {
  result: FrontierResult;
  chosen: { service_level: number; expected_total_cost_annual: number; inventory_value: number; expected_fill_rate: number; recommended_order_qty: number; safety_stock: number } | null;
  sl: number;
  setSl: (v: number) => void;
}) {
  const W = 700, H = 320;
  const padL = 56, padR = 24, padT = 12, padB = 40;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const pts = result.points;
  const minCost = Math.min(...pts.map((p) => p.expected_total_cost_annual));
  const maxCost = Math.max(...pts.map((p) => p.expected_total_cost_annual));
  const minSL = Math.min(...pts.map((p) => p.service_level));
  const maxSL = Math.max(...pts.map((p) => p.service_level));

  const slToX = (s: number) => padL + ((s - minSL) / (maxSL - minSL || 1)) * innerW;
  const costToY = (c: number) => padT + innerH - ((c - minCost) / (maxCost - minCost || 1)) * innerH;

  return (
    <div className="rounded-lg border bg-card p-4">
      <header className="mb-2 flex items-baseline justify-between">
        <div>
          <h3 className="text-sm font-semibold">Cost vs service-level frontier</h3>
          <p className="text-xs text-muted-foreground">
            {result.sku_id} · default policy: {result.policy_name}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          baseline SL = {(result.baseline_service_level * 100).toFixed(0)}%
        </p>
      </header>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={padL} y1={padT + innerH} x2={padL + innerW} y2={padT + innerH} stroke="currentColor" strokeOpacity={0.3} />
        <line x1={padL} y1={padT} x2={padL} y2={padT + innerH} stroke="currentColor" strokeOpacity={0.3} />
        <polyline
          fill="none"
          stroke="hsl(215 70% 50%)"
          strokeWidth={2}
          points={pts.map((p) => `${slToX(p.service_level)},${costToY(p.expected_total_cost_annual)}`).join(" ")}
        />
        {pts.map((p, i) => (
          <circle key={i} cx={slToX(p.service_level)} cy={costToY(p.expected_total_cost_annual)} r={3} fill="hsl(215 70% 50%)" />
        ))}
        {chosen && (
          <g>
            <circle cx={slToX(chosen.service_level)} cy={costToY(chosen.expected_total_cost_annual)} r={6} fill="hsl(0 70% 55%)" />
            <line
              x1={slToX(chosen.service_level)}
              y1={padT}
              x2={slToX(chosen.service_level)}
              y2={padT + innerH}
              stroke="hsl(0 70% 55%)"
              strokeOpacity={0.4}
              strokeDasharray="3 3"
            />
          </g>
        )}
        {[minSL, (minSL + maxSL) / 2, maxSL].map((s, i) => (
          <text key={i} x={slToX(s)} y={H - 18} textAnchor="middle" fontSize="10" fill="currentColor" opacity={0.6}>
            {(s * 100).toFixed(0)}%
          </text>
        ))}
        {[minCost, (minCost + maxCost) / 2, maxCost].map((c, i) => (
          <text key={i} x={padL - 6} y={costToY(c) + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity={0.6}>
            ${(c / 1000).toFixed(1)}k
          </text>
        ))}
        <text x={padL + innerW / 2} y={H - 4} textAnchor="middle" fontSize="11" fill="currentColor" opacity={0.7}>
          Service level
        </text>
      </svg>
      <div className="mt-3 flex items-center gap-3">
        <label className="flex flex-1 items-center gap-2 text-sm">
          Target SL: <span className="font-semibold">{(sl * 100).toFixed(0)}%</span>
          <input
            type="range"
            min={Math.round(minSL * 100)}
            max={Math.round(maxSL * 100)}
            step={1}
            value={Math.round(sl * 100)}
            onChange={(e) => setSl(parseInt(e.target.value) / 100)}
            className="flex-1"
          />
        </label>
      </div>
      {chosen && (
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <Stat
            label="Recommended Q"
            value={chosen.recommended_order_qty.toFixed(0)}
            help="Order quantity from the multi-period (s, S) policy at the chosen service level. This is what you'd actually place each cycle to keep on-hand healthy across many review periods. Different from Q* below — see the Newsvendor card."
          />
          <Stat
            label="Safety stock"
            value={chosen.safety_stock.toFixed(0)}
            help="Buffer above expected lead-time demand. Sized so the cycle service level matches the slider — higher SL → bigger buffer."
          />
          <Stat
            label="Inventory $"
            value={`$${(chosen.inventory_value / 1000).toFixed(1)}k`}
            help="Average dollars tied up in stock (Q/2 + safety) × unit cost. Working-capital draw."
          />
          <Stat
            label="Total cost"
            value={`$${(chosen.expected_total_cost_annual / 1000).toFixed(1)}k`}
            help="Holding + ordering + expected stockout cost, annualized. The y-axis on the frontier chart."
          />
        </div>
      )}
    </div>
  );
}

function NewsvendorPanel({ result }: { result: FrontierResult }) {
  const [salvage, setSalvage] = useState(0);
  const cu = result.unit_price - result.unit_cost;
  const co = Math.max(0.01, result.unit_cost - salvage);
  const cr = cu / (cu + co);

  // Recommended Q comes from the slider's chosen point on the (s,S) frontier — different
  // problem from Q*. Show a side-by-side comparison if both are available.
  const baselinePoint = result.points.find(
    (p) => Math.abs(p.service_level - result.baseline_service_level) < 1e-3,
  ) ?? result.points[Math.floor(result.points.length / 2)];

  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="text-sm font-semibold">
        Newsvendor calculator
        <HelpTooltip text="Newsvendor solves the single-period stocking problem (perishables, fashion drops, one-time orders). Picks Q* that minimizes expected overage + underage cost, ignoring future periods." />
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Single-period optimal Q*. F⁻¹(critical ratio) on the demand distribution.
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-3">
        <Field label="Unit cost" value={`$${result.unit_cost.toFixed(2)}`} />
        <Field label="Unit price" value={`$${result.unit_price.toFixed(2)}`} />
        <label className="block">
          <span className="text-foreground">Salvage value</span>
          <input
            type="number"
            step="0.01"
            value={salvage}
            onChange={(e) => setSalvage(parseFloat(e.target.value) || 0)}
            className="mt-1 h-8 w-full rounded border border-input bg-background px-2 text-foreground"
          />
        </label>
        <Stat
          label="Underage cost (Cu)"
          value={`$${cu.toFixed(2)}`}
          help="Margin lost per unit of unmet demand. Cu = unit price − unit cost."
        />
        <Stat
          label="Overage cost (Co)"
          value={`$${co.toFixed(2)}`}
          help="Loss per leftover unit at end of period. Co = unit cost − salvage value."
        />
        <Stat
          label="Critical ratio"
          value={cr.toFixed(3)}
          help="CR = Cu / (Cu + Co). The newsvendor target service level for this SKU's economics."
        />
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        Cu = price − cost = ${cu.toFixed(2)}. Co = cost − salvage = ${co.toFixed(2)}. CR = Cu/(Cu+Co) = {cr.toFixed(3)}.
        Optimal Q* = F⁻¹(CR) on the demand distribution.
      </p>

      {result.newsvendor && (
        <div className="mt-4 rounded-md border border-border bg-muted/30 p-3">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Q vs Q*
            <HelpTooltip text="Recommended Q (left) is from the multi-period (s, S) policy at your slider's service level — what to order each replenishment cycle. Q* (right) is the single-period newsvendor optimum — what to order if this is a perishable or one-shot decision. They answer different questions and will rarely match." />
          </p>
          <div className="mt-2 grid grid-cols-2 gap-3 text-sm">
            <Stat
              label="Recommended Q (multi-period)"
              value={baselinePoint.recommended_order_qty.toFixed(0)}
              help={`From the (s, S) policy at ${(baselinePoint.service_level * 100).toFixed(0)}% service level — the order qty per cycle.`}
            />
            <Stat
              label="Q* (single-period)"
              value={result.newsvendor.optimal_qty.toFixed(0)}
              help="Newsvendor-optimal quantity for a single-period decision. F⁻¹(critical ratio) on the demand distribution."
            />
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            They differ because they answer different questions: Q assumes you replenish every
            cycle and balances holding + stockout cost over time; Q* assumes one shot and balances
            leftover (Co) against unmet demand (Cu).
          </p>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, help }: { label: string; value: string; help?: string }) {
  return (
    <div className="rounded border border-border bg-background px-2 py-1.5">
      <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
        {label}
        {help && <HelpTooltip text={help} />}
      </p>
      <p className="font-semibold tabular-nums text-foreground">{value}</p>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="block">
      <p className="text-foreground">{label}</p>
      <p className="mt-1 flex h-8 items-center rounded border border-input bg-muted px-2 text-foreground tabular-nums">
        {value}
      </p>
    </div>
  );
}
