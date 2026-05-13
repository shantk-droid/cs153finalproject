import { notFound } from "next/navigation";
import { ForecastsTable } from "@/components/ForecastsTable";
import { serverFetch } from "@/lib/api-server";
import type { SkuTableRow } from "@/lib/types";

export const dynamic = "force-dynamic";

async function getRows(id: string): Promise<SkuTableRow[] | null> {
  return serverFetch<SkuTableRow[]>(
    `/datasets/${encodeURIComponent(id)}/skus?limit=2000&sort_by=days_of_cover&sort_dir=asc&include_history=true`,
  );
}

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ForecastsPage({ params }: Props) {
  const { id } = await params;
  const rows = await getRows(id);
  if (!rows) notFound();
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Forecasting</p>
        <h1 className="text-2xl font-semibold tracking-tight">Forecasts &amp; reorder queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Sorted by days-of-cover. Click any tile to filter — or any SKU for decomposition + policy detail.
        </p>
      </header>
      <ForecastsTable rows={rows} datasetId={id} />
    </main>
  );
}
