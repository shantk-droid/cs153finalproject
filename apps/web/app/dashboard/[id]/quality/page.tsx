import { notFound } from "next/navigation";
import { DataQualityReportView } from "@/components/DataQualityReport";
import { serverFetch } from "@/lib/api-server";
import type { DataQualityReport } from "@/lib/types";

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

async function fetchReport(id: string, explain = false): Promise<DataQualityReport | null> {
  return serverFetch<DataQualityReport>(
    `/datasets/${encodeURIComponent(id)}/quality${explain ? "?explain=true" : ""}`,
  );
}

export default async function QualityPage({ params }: Props) {
  const { id } = await params;
  const report = await fetchReport(id);
  if (!report) notFound();

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Data quality</p>
        <h1 className="text-2xl font-semibold tracking-tight">Composite report</h1>
      </header>
      <DataQualityReportView report={report} />
    </main>
  );
}
