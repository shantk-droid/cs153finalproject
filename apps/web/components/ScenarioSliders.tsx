"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { runScenario } from "@/lib/api-client";
import type { Recommendation, RecommendationOverrides, ScenarioResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  datasetId: string;
  skuId: string;
  base: Recommendation;
}

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}

function Slider({ label, value, min, max, step, format, onChange }: SliderProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-xs">
        <label className="font-medium">{label}</label>
        <span className="font-mono tabular-nums text-muted-foreground">{format(value)}</span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
    </div>
  );
}

const DEBOUNCE_MS = 350;

interface SavedScenario {
  id: string;
  service_level: number;
  lead_mult: number;
  holding_rate: number;
  scenario: Recommendation;
}

export function ScenarioSliders({ datasetId, skuId, base }: Props) {
  const baseServiceLevel = 0.95;
  const baseLeadMult = 1.0;
  const baseHoldingRate = 0.25;

  const [serviceLevel, setServiceLevel] = useState(baseServiceLevel);
  const [leadMult, setLeadMult] = useState(baseLeadMult);
  const [holdingRate, setHoldingRate] = useState(baseHoldingRate);
  const [response, setResponse] = useState<ScenarioResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedScenario[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isModified = useMemo(
    () =>
      Math.abs(serviceLevel - baseServiceLevel) > 1e-6 ||
      Math.abs(leadMult - baseLeadMult) > 1e-6 ||
      Math.abs(holdingRate - baseHoldingRate) > 1e-6,
    [serviceLevel, leadMult, holdingRate],
  );

  useEffect(() => {
    if (!isModified) {
      setResponse(null);
      return;
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const overrides: RecommendationOverrides = {
        service_level: serviceLevel,
        holding_cost_rate: holdingRate,
      };
      // Apply lead-time as a multiplier of the SKU's base average. We pass an absolute
      // override; the backend's `lead_time_days_override` overrides the gamma fit entirely.
      // If we don't have a base lead time on hand, fall through and let the backend default
      // — the user still gets service level and holding rate updates.
      const baseLt =
        base.parameters && typeof base.parameters["lead_time_days"] === "number"
          ? Number(base.parameters["lead_time_days"])
          : null;
      if (baseLt != null && Math.abs(leadMult - 1.0) > 1e-6) {
        overrides.lead_time_days_override = baseLt * leadMult;
      }

      setPending(true);
      setError(null);
      try {
        const r = await runScenario(datasetId, skuId, overrides);
        setResponse(r);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setPending(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [serviceLevel, leadMult, holdingRate, isModified, datasetId, skuId, base.parameters]);

  function reset() {
    setServiceLevel(baseServiceLevel);
    setLeadMult(baseLeadMult);
    setHoldingRate(baseHoldingRate);
    setResponse(null);
  }

  function saveScenario() {
    if (!response) return;
    const id = `${Date.now().toString(36)}`;
    setSaved((prev) => [
      ...prev.slice(-3),
      {
        id,
        service_level: serviceLevel,
        lead_mult: leadMult,
        holding_rate: holdingRate,
        scenario: response.scenario,
      },
    ]);
  }

  const scenario = response?.scenario;
  const baseRec = response?.base ?? base;

  return (
    <div className="space-y-4 rounded-lg border bg-card p-4">
      <header className="flex items-baseline justify-between">
        <div>
          <h3 className="text-sm font-semibold">What-if scenario</h3>
          <p className="text-xs text-muted-foreground">
            Move sliders to override defaults; results update live.
          </p>
        </div>
        {isModified && (
          <button
            type="button"
            onClick={reset}
            className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          >
            Reset to model-optimal
          </button>
        )}
      </header>

      <div className="space-y-3">
        <Slider
          label="Service level"
          value={serviceLevel}
          min={0.80}
          max={0.999}
          step={0.01}
          format={(v) => `${(v * 100).toFixed(1)}%`}
          onChange={setServiceLevel}
        />
        <Slider
          label="Lead-time multiplier"
          value={leadMult}
          min={0.5}
          max={3.0}
          step={0.05}
          format={(v) => `${v.toFixed(2)}×`}
          onChange={setLeadMult}
        />
        <Slider
          label="Holding cost rate"
          value={holdingRate}
          min={0.05}
          max={0.50}
          step={0.01}
          format={(v) => `${(v * 100).toFixed(0)}%`}
          onChange={setHoldingRate}
        />
      </div>

      {pending && <p className="text-xs text-muted-foreground">re-running…</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}

      {scenario && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2 rounded-md border bg-muted/30 p-3 text-xs">
            <DiffRow
              label="Order qty"
              base={baseRec.recommended_order_qty}
              scenario={scenario.recommended_order_qty}
            />
            {baseRec.reorder_point !== null && scenario.reorder_point !== null && (
              <DiffRow
                label="Reorder point"
                base={baseRec.reorder_point}
                scenario={scenario.reorder_point}
              />
            )}
            <DiffRow label="Safety stock" base={baseRec.safety_stock} scenario={scenario.safety_stock} />
            <DiffRow
              label="P(stockout)"
              base={baseRec.expected_stockout_prob}
              scenario={scenario.expected_stockout_prob}
              format={(v) => `${(v * 100).toFixed(2)}%`}
              upIsBad
            />
            <DiffRow
              label="Fill rate"
              base={baseRec.expected_fill_rate}
              scenario={scenario.expected_fill_rate}
              format={(v) => `${(v * 100).toFixed(2)}%`}
            />
            <DiffRow
              label="Annual cost"
              base={baseRec.expected_total_cost_annual}
              scenario={scenario.expected_total_cost_annual}
              format={(v) => `$${v.toFixed(0)}`}
              upIsBad
            />
          </div>
          <button
            type="button"
            onClick={saveScenario}
            className="rounded-md border border-input bg-background px-2 py-1 text-[11px] hover:bg-muted"
          >
            Save as scenario
          </button>
        </div>
      )}

      {saved.length > 0 && (
        <div className="space-y-2 rounded-md border border-dashed p-3">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Saved</p>
          {saved.map((s) => (
            <div key={s.id} className="flex items-center justify-between text-[11px]">
              <span className="text-muted-foreground">
                {(s.service_level * 100).toFixed(0)}% SL · {s.lead_mult.toFixed(2)}× LT ·{" "}
                {(s.holding_rate * 100).toFixed(0)}% holding
              </span>
              <span className="tabular-nums">
                ${Math.round(s.scenario.expected_total_cost_annual)} / yr
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DiffRow({
  label,
  base,
  scenario,
  format = (v) => v.toFixed(1),
  upIsBad = false,
}: {
  label: string;
  base: number;
  scenario: number;
  format?: (v: number) => string;
  upIsBad?: boolean;
}) {
  const delta = scenario - base;
  const pct = base !== 0 ? delta / base : 0;
  const isUp = delta > 1e-9;
  const isDown = delta < -1e-9;
  const goodColor = "text-emerald-600 dark:text-emerald-400";
  const badColor = "text-destructive";
  const upClass = upIsBad ? badColor : goodColor;
  const downClass = upIsBad ? goodColor : badColor;
  return (
    <div className="space-y-0.5">
      <p className="text-muted-foreground">{label}</p>
      <p className="font-mono tabular-nums">
        {format(scenario)}
        {(isUp || isDown) && (
          <span className={cn("ml-1.5", isUp ? upClass : downClass)}>
            {isUp ? "▲" : "▼"} {format(Math.abs(delta))}
            {Math.abs(pct) > 0.001 && ` (${(pct * 100).toFixed(0)}%)`}
          </span>
        )}
      </p>
    </div>
  );
}
