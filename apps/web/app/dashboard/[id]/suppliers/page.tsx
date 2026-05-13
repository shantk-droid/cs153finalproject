import Link from "next/link";
import { Truck } from "lucide-react";
import { HelpTooltip } from "@/components/HelpTooltip";
import { LlmInsightsPanel } from "@/components/LlmInsightsPanel";
import { serverFetch } from "@/lib/api-server";
import { deriveSupplierInsights, summarizeSuppliers } from "@/lib/insights";
import type { SupplierScorecard } from "@/lib/types";

const COLUMN_HELP: Record<string, string> = {
  supplier:
    "Vendor name and country. Click to open the supplier scorecard with full receipt history, lead-time histogram, and Bayesian posterior overlay.",
  n_skus: "Distinct SKUs sourced from this supplier across the panel.",
  annual_revenue:
    "Annualized revenue from these SKUs (sum of demand × unit_price scaled to a 365-day year). Bigger = more dependence.",
  avg_lt:
    "Mean of actual lead times observed in the receipts table: received_date − ordered_date. Empty if no receipts yet.",
  lt_sigma:
    "Std. deviation of actual lead times. Higher = more variable supplier; widens safety stock.",
  otif:
    "On-Time, In-Full. % of receipts where received_date ≤ expected_date AND received_qty ≥ 99% of ordered_qty. <75% triggers an insights tile alert.",
  on_time: "% of receipts that arrived on or before the expected date (the time half of OTIF).",
  in_full:
    "% of receipts where received_qty ≥ 99% of ordered_qty (the quantity half of OTIF). <99% indicates partial shipments.",
  moq:
    "Minimum order quantity. The reorder queue rounds recommended_qty up to this floor (and to the case-pack multiple).",
  terms:
    "Payment terms parsed to days (e.g. Net 30 → 30). Drives the DPO term in the working-capital cash-to-cash cycle.",
};

export const dynamic = "force-dynamic";

async function getSuppliers(id: string): Promise<SupplierScorecard[]> {
  const data = await serverFetch<SupplierScorecard[]>(
    `/datasets/${encodeURIComponent(id)}/suppliers`,
  );
  return data ?? [];
}

function formatPct(p: number | null | undefined): string {
  if (p === null || p === undefined) return "—";
  return `${p.toFixed(0)}%`;
}

function formatNum(n: number | null | undefined, dec = 1): string {
  if (n === null || n === undefined) return "—";
  return n.toFixed(dec);
}

function otifColor(p: number | null | undefined): string {
  if (p === null || p === undefined) return "text-muted-foreground";
  if (p >= 90) return "text-green-600";
  if (p >= 75) return "text-amber-600";
  return "text-red-600";
}

interface Props {
  params: Promise<{ id: string }>;
}

export default async function SuppliersPage({ params }: Props) {
  const { id } = await params;
  const suppliers = await getSuppliers(id);
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Procurement</p>
        <h1 className="text-2xl font-semibold tracking-tight">Supplier scorecards</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          OTIF, lead time mean ± std, MOQ. Lead-time posterior updates from receipts.
        </p>
      </header>

      {suppliers.length > 0 && (
        <LlmInsightsPanel
          datasetId={id}
          variant="supplier"
          heuristics={deriveSupplierInsights(suppliers)}
          summary={summarizeSuppliers(suppliers)}
        />
      )}

      {suppliers.length === 0 ? (
        <div className="rounded-lg border border-dashed bg-muted/30 p-8 text-center text-sm text-muted-foreground">
          No supplier data found for this dataset.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">
                  Supplier
                  <HelpTooltip text={COLUMN_HELP.supplier} />
                </th>
                <th className="px-3 py-2 text-right">
                  # SKUs
                  <HelpTooltip text={COLUMN_HELP.n_skus} />
                </th>
                <th className="px-3 py-2 text-right">
                  Annual rev
                  <HelpTooltip text={COLUMN_HELP.annual_revenue} />
                </th>
                <th className="px-3 py-2 text-right">
                  Avg LT (d)
                  <HelpTooltip text={COLUMN_HELP.avg_lt} />
                </th>
                <th className="px-3 py-2 text-right">
                  LT σ
                  <HelpTooltip text={COLUMN_HELP.lt_sigma} />
                </th>
                <th className="px-3 py-2 text-right">
                  OTIF
                  <HelpTooltip text={COLUMN_HELP.otif} />
                </th>
                <th className="px-3 py-2 text-right">
                  On-time
                  <HelpTooltip text={COLUMN_HELP.on_time} />
                </th>
                <th className="px-3 py-2 text-right">
                  In-full
                  <HelpTooltip text={COLUMN_HELP.in_full} />
                </th>
                <th className="px-3 py-2 text-right">
                  MOQ
                  <HelpTooltip text={COLUMN_HELP.moq} />
                </th>
                <th className="px-3 py-2 text-left">
                  Terms
                  <HelpTooltip text={COLUMN_HELP.terms} align="end" />
                </th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <tr key={s.supplier_id} className="border-t">
                  <td className="px-3 py-2">
                    <Link
                      href={`/dashboard/${id}/suppliers/${encodeURIComponent(s.supplier_id)}`}
                      className="inline-flex items-center gap-2 font-medium hover:underline"
                    >
                      <Truck className="h-3.5 w-3.5 text-muted-foreground" />
                      {s.name}
                    </Link>
                    {s.country && (
                      <span className="ml-2 text-[11px] text-muted-foreground">{s.country}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.n_skus}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    ${(s.annual_revenue / 1000).toFixed(0)}k
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatNum(s.avg_lead_time_days, 1)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatNum(s.lead_time_std_days, 1)}</td>
                  <td className={`px-3 py-2 text-right font-medium tabular-nums ${otifColor(s.otif_pct)}`}>
                    {formatPct(s.otif_pct)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatPct(s.on_time_pct)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatPct(s.in_full_pct)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.moq ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{s.payment_terms ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
