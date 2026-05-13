"use client";

import { useState } from "react";
import { Loader2, Zap, AlertTriangle } from "lucide-react";
import { HelpTooltip } from "@/components/HelpTooltip";
import { cn } from "@/lib/utils";
import type { StressTestResult } from "@/lib/types";

export function StressTestClient({ datasetId }: { datasetId: string }) {
  const [ltMult, setLtMult] = useState(1.5);
  const [demandMult, setDemandMult] = useState(1.0);
  const [sl, setSl] = useState(0.95);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<StressTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const r = await fetch(`/api/datasets/${datasetId}/stress_test`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          lead_time_multiplier: ltMult,
          demand_multiplier: demandMult,
          service_level: sl,
        }),
      });
      if (!r.ok) throw new Error(`API ${r.status}`);
      const data = (await r.json()) as StressTestResult;
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "stress test failed");
    } finally {
      setRunning(false);
    }
  }

  const dirtied = ltMult !== 1.0 || demandMult !== 1.0;

  return (
    <div className="space-y-6">
      <section className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-semibold">Shock parameters</h3>
        <div className="mt-3 grid gap-4 md:grid-cols-3">
          <Slider
            label={`Lead-time multiplier: ${ltMult.toFixed(2)}×`}
            help="Multiplies every SKU's lead time by this factor. 1.5× simulates a port slowdown; 2× simulates a major supply disruption. Lower (e.g. 0.7×) tests the upside of expediting."
            value={ltMult}
            min={0.5}
            max={2}
            step={0.05}
            onChange={setLtMult}
          />
          <Slider
            label={`Demand multiplier: ${demandMult.toFixed(2)}×`}
            help="Multiplies forecast demand panel-wide. 1.5× simulates a viral spike or promo lift; 0.7× tests recession scenarios."
            value={demandMult}
            min={0.5}
            max={2}
            step={0.05}
            onChange={setDemandMult}
          />
          <Slider
            label={`Service level target: ${(sl * 100).toFixed(0)}%`}
            help="Target cycle service level — the policy will size safety stock to hit this fraction of cycles without stockout, on top of the shocked inputs."
            value={sl}
            min={0.85}
            max={0.99}
            step={0.01}
            onChange={setSl}
          />
        </div>
        <button
          type="button"
          onClick={run}
          disabled={running || !dirtied}
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
          Run stress test
        </button>
        {!dirtied && (
          <p className="mt-2 text-xs text-muted-foreground">
            Move a slider away from 1.0× to enable.
          </p>
        )}
        {error && (
          <p className="mt-2 text-xs text-red-600">{error}</p>
        )}
      </section>

      {result && (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <Card
              label="Δ revenue at risk"
              help="Change in panel-total revenue at risk: shock minus baseline. Positive = the shock exposes more dollars than the steady state."
              value={`$${(result.delta_total_revenue_at_risk / 1000).toFixed(1)}k`}
              negative={result.delta_total_revenue_at_risk > 0}
            />
            <Card
              label="VaR 95%"
              help="Value at Risk at 95%. The dollar loss the worst-case 5% of SKUs would incur under the shock — i.e. 95% of SKUs lose less than this."
              value={`$${(result.var_95 / 1000).toFixed(1)}k`}
            />
            <Card
              label="CVaR 95%"
              help="Conditional VaR (a.k.a. expected shortfall). The average loss across the worst 5% of SKUs. Always ≥ VaR; how bad it gets when it gets bad."
              value={`$${(result.cvar_95 / 1000).toFixed(1)}k`}
            />
            <Card
              label="SKUs at risk"
              help="Count of SKUs with elevated stockout probability — shock count vs baseline count. Wider gap = the shock reaches deeper into the catalog."
              value={`${result.shock_n_at_risk} / ${result.baseline_n_at_risk} base`}
            />
          </section>

          <section className="rounded-lg border bg-card">
            <header className="border-b px-4 py-3">
              <h3 className="text-sm font-semibold">Top impacted SKUs</h3>
              <p className="text-xs text-muted-foreground">Largest shock-vs-baseline gap in revenue at risk</p>
            </header>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left">SKU</th>
                    <th className="px-3 py-2 text-right">
                      Stockout % base
                      <HelpTooltip text="Probability of stockout in a replenishment cycle under the SKU's normal lead time and forecast demand." />
                    </th>
                    <th className="px-3 py-2 text-right">
                      Stockout % shock
                      <HelpTooltip text="Stockout probability with your slider's lead-time × demand multipliers applied. Bigger gap to baseline = more exposed." />
                    </th>
                    <th className="px-3 py-2 text-right">
                      $ at risk base
                      <HelpTooltip text="Stockout probability × annualized revenue at the baseline. The expected dollar value of unmet demand without the shock." />
                    </th>
                    <th className="px-3 py-2 text-right">
                      $ at risk shock
                      <HelpTooltip text="Same calculation under the shock. The expected dollar value of unmet demand if the shock happened." />
                    </th>
                    <th className="px-3 py-2 text-right">
                      Δ $ at risk
                      <HelpTooltip text="Shock minus baseline. Red = additional revenue the shock would put at risk vs steady state." />
                    </th>
                    <th className="px-3 py-2 text-right">
                      Q base → shock
                      <HelpTooltip
                        text="Recommended order quantity under baseline → shock. Shows how the policy adjusts: typically rises under longer lead times or higher demand to protect the same service level."
                        align="end"
                      />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.top_impacted.map((s) => (
                    <tr key={s.sku_id} className="border-t">
                      <td className="px-3 py-1.5 font-mono text-xs">{s.sku_id}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{(s.baseline_stockout_prob * 100).toFixed(0)}%</td>
                      <td className="px-3 py-1.5 text-right tabular-nums font-medium">{(s.shock_stockout_prob * 100).toFixed(0)}%</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">${(s.baseline_revenue_at_risk / 1000).toFixed(1)}k</td>
                      <td className="px-3 py-1.5 text-right tabular-nums font-medium">${(s.shock_revenue_at_risk / 1000).toFixed(1)}k</td>
                      <td className={cn("px-3 py-1.5 text-right tabular-nums", s.delta_revenue_at_risk > 0 ? "text-red-600" : "text-emerald-600")}>
                        ${(s.delta_revenue_at_risk / 1000).toFixed(1)}k
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums text-xs text-muted-foreground">
                        {s.baseline_recommended_qty.toFixed(0)} → {s.shock_recommended_qty.toFixed(0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function Slider({
  label,
  help,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  help?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="font-medium">
        {label}
        {help && <HelpTooltip text={help} />}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="mt-2 w-full accent-primary"
      />
      <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>{min}</span>
        <span>1.0</span>
        <span>{max}</span>
      </div>
    </label>
  );
}

function Card({
  label,
  help,
  value,
  negative,
}: {
  label: string;
  help?: string;
  value: string;
  negative?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2">
        <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
          {label}
          {help && <HelpTooltip text={help} />}
        </p>
        {negative && <AlertTriangle className="h-3 w-3 text-amber-600" />}
      </div>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
