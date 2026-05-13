import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { LeadTimeHistogram } from "@/components/LeadTimeHistogram";
import { HelpTooltip } from "@/components/HelpTooltip";
import { serverFetch } from "@/lib/api-server";
import type { SupplierDetail } from "@/lib/types";

const CARD_HELP: Record<string, string> = {
  n_skus: "Distinct SKUs sourced from this supplier across the panel.",
  default_lt:
    "Prior lead time mean (days), seeded from the supplier metadata or panel average. Used as the gamma prior before any receipts arrive.",
  lt_std:
    "Prior lead-time std deviation (days). Wider prior = lower confidence; receipts shift faster.",
  posterior:
    "Bayesian posterior lead-time mean ± std after combining the prior with observed receipts (gamma + normal-approx conjugate update). What the recommend pipeline actually uses.",
  moq: "Minimum order quantity floor for any PO with this supplier.",
  case_pack: "Order size must be a multiple of this value (e.g. 12 = full case).",
  terms:
    "Payment terms parsed to days (Net 30 → 30). Drives DPO in the cash-to-cash cycle.",
  receipts: "Historical receipt count used by the posterior + OTIF metrics.",
};

export const dynamic = "force-dynamic";

async function getDetail(id: string, sid: string): Promise<SupplierDetail | null> {
  return serverFetch<SupplierDetail>(
    `/datasets/${encodeURIComponent(id)}/suppliers/${encodeURIComponent(sid)}`,
  );
}

interface Props {
  params: Promise<{ id: string; supplierId: string }>;
}

export default async function SupplierDetailPage({ params }: Props) {
  const { id, supplierId } = await params;
  const detail = await getDetail(id, supplierId);
  if (!detail) notFound();

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
      <Link
        href={`/dashboard/${id}/suppliers`}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline"
      >
        <ArrowLeft className="h-3 w-3" />
        All suppliers
      </Link>
      <header className="flex items-baseline justify-between">
        <div>
          <p className="text-xs uppercase tracking-widest text-muted-foreground">Supplier</p>
          <h1 className="text-2xl font-semibold tracking-tight">{detail.name}</h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{detail.supplier_id}</p>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <p>{detail.country ?? ""}</p>
          <p>{detail.contact_email ?? ""}</p>
        </div>
      </header>

      <section className="grid gap-3 md:grid-cols-4">
        <Card label="# SKUs" help={CARD_HELP.n_skus} value={detail.n_skus.toString()} />
        <Card label="Default LT" help={CARD_HELP.default_lt} value={`${detail.default_lead_time_days?.toFixed(1) ?? "—"}d`} />
        <Card label="LT std" help={CARD_HELP.lt_std} value={`${detail.lead_time_std_days?.toFixed(1) ?? "—"}d`} />
        <Card label="Posterior LT" help={CARD_HELP.posterior} value={
          detail.leadtime_posterior_mean !== null && detail.leadtime_posterior_mean !== undefined
            ? `${detail.leadtime_posterior_mean.toFixed(1)} ± ${(detail.leadtime_posterior_std ?? 0).toFixed(1)}d`
            : "—"
        } />
        <Card label="MOQ" help={CARD_HELP.moq} value={detail.moq?.toString() ?? "—"} />
        <Card label="Case pack" help={CARD_HELP.case_pack} value={detail.case_pack?.toString() ?? "—"} />
        <Card label="Terms" help={CARD_HELP.terms} value={detail.payment_terms ?? "—"} />
        <Card label="Receipts" help={CARD_HELP.receipts} value={detail.receipts.length.toString()} />
      </section>

      {detail.actual_lead_times.length > 0 && (
        <section className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-semibold">Lead-time distribution</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Histogram of actual lead times from {detail.receipts.length} historical receipts. Posterior
            shifts the prior toward observed reality.
          </p>
          <div className="mt-3">
            <LeadTimeHistogram
              observed={detail.actual_lead_times}
              priorMean={detail.default_lead_time_days ?? null}
              priorStd={detail.lead_time_std_days ?? null}
              posteriorMean={detail.leadtime_posterior_mean ?? null}
              posteriorStd={detail.leadtime_posterior_std ?? null}
            />
          </div>
        </section>
      )}

      <section className="rounded-lg border bg-card">
        <header className="border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Receipt history</h2>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Receipt</th>
                <th className="px-3 py-2 text-left">SKU</th>
                <th className="px-3 py-2 text-left">Ordered</th>
                <th className="px-3 py-2 text-left">Expected</th>
                <th className="px-3 py-2 text-left">Received</th>
                <th className="px-3 py-2 text-right">Actual LT (d)</th>
                <th className="px-3 py-2 text-right">Ordered qty</th>
                <th className="px-3 py-2 text-right">Received qty</th>
              </tr>
            </thead>
            <tbody>
              {detail.receipts.slice(0, 50).map((r) => {
                const od = new Date(r.ordered_date);
                const rd = new Date(r.received_date);
                const lt = (rd.getTime() - od.getTime()) / 86400000;
                const partial = r.received_qty < r.ordered_qty * 0.99;
                return (
                  <tr key={r.receipt_id} className="border-t">
                    <td className="px-3 py-2 font-mono text-xs">{r.receipt_id}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.sku_id}</td>
                    <td className="px-3 py-2 text-xs">{r.ordered_date}</td>
                    <td className="px-3 py-2 text-xs">{r.expected_date}</td>
                    <td className="px-3 py-2 text-xs">{r.received_date}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{lt.toFixed(1)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.ordered_qty.toFixed(0)}</td>
                    <td className={`px-3 py-2 text-right tabular-nums ${partial ? "text-amber-600" : ""}`}>
                      {r.received_qty.toFixed(0)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function Card({ label, value, help }: { label: string; value: string; help?: string }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2">
      <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
        {label}
        {help && <HelpTooltip text={help} />}
      </p>
      <p className="text-base font-semibold tabular-nums">{value}</p>
    </div>
  );
}
