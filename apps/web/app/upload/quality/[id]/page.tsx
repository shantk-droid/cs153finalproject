import Link from "next/link";
import { notFound } from "next/navigation";
import { DataQualityReportView } from "@/components/DataQualityReport";
import { serverFetch } from "@/lib/api-server";
import type { DataQualityReport } from "@/lib/types";

export const dynamic = "force-dynamic";

async function fetchReport(id: string): Promise<DataQualityReport | null> {
  return serverFetch<DataQualityReport>(`/datasets/${encodeURIComponent(id)}/quality`);
}

interface Props {
  params: Promise<{ id: string }>;
}

export default async function QualityPage({ params }: Props) {
  const { id } = await params;
  const report = await fetchReport(id);
  if (!report) notFound();

  const hasHardFail = report.assertions.some((a) => a.severity === "hard");

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <DataQualityReportView report={report} />

      <div className="mt-10 flex items-center justify-between gap-3 border-t pt-6">
        <Link
          href="/upload"
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          ← Upload a different file
        </Link>
        {!hasHardFail && (
          <Link
            href={`/dashboard/${id}`}
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Continue to dashboard →
          </Link>
        )}
      </div>
    </main>
  );
}
