import { headers } from "next/headers";
import { Wallet, ArrowRight } from "lucide-react";
import type { WorkingCapital } from "@/lib/types";

async function fetchWC(datasetId: string): Promise<WorkingCapital | null> {
  const h = await headers();
  const host = h.get("host");
  const proto = h.get("x-forwarded-proto") ?? "http";
  try {
    const r = await fetch(`${proto}://${host}/api/datasets/${encodeURIComponent(datasetId)}/working_capital`, {
      cache: "no-store",
    });
    if (!r.ok) return null;
    return (await r.json()) as WorkingCapital;
  } catch {
    return null;
  }
}

export async function WorkingCapitalTile({ datasetId }: { datasetId: string }) {
  const wc = await fetchWC(datasetId);
  if (!wc) return null;

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2">
        <Wallet className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold">Working capital</h3>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <Stat label="Inventory $" value={`$${(wc.inventory_value / 1000).toFixed(0)}k`} />
        <Stat label="Annual COGS" value={`$${(wc.annual_cogs / 1000).toFixed(0)}k`} />
        <Stat label="DIO" value={wc.dio_days === null ? "—" : `${wc.dio_days.toFixed(0)}d`} />
        <Stat label="DPO" value={wc.dpo_days === null ? "—" : `${wc.dpo_days.toFixed(0)}d`} />
      </div>

      <div className="mt-3 rounded border bg-muted/30 p-2 text-center">
        <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
          Cash-to-cash cycle
        </p>
        <p className="text-2xl font-bold tabular-nums">
          {wc.cash_to_cash_days === null ? "—" : `${wc.cash_to_cash_days.toFixed(0)}d`}
        </p>
        <p className="text-[10px] text-muted-foreground">DIO + DSO − DPO (DSO = 0 assumption)</p>
      </div>

      {wc.by_supplier.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
            Top suppliers (payable outstanding)
          </p>
          <ul className="mt-1 space-y-0.5">
            {wc.by_supplier.slice(0, 3).map((s) => (
              <li key={s.supplier_id} className="flex items-center justify-between text-xs">
                <span className="truncate">{s.supplier_name}</span>
                <span className="tabular-nums text-muted-foreground">
                  ${(s.payable_outstanding / 1000).toFixed(1)}k
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-widest text-muted-foreground">{label}</p>
      <p className="font-semibold tabular-nums">{value}</p>
    </div>
  );
}
