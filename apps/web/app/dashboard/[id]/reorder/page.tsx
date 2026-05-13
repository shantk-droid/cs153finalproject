import { ReorderPageClient } from "@/components/ReorderPageClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ReorderPage({ params }: Props) {
  const { id } = await params;
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Action layer</p>
        <h1 className="text-2xl font-semibold tracking-tight">Reorder queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ranked by stockout-risk × revenue. Draft a PO with one click.
        </p>
      </header>
      <ReorderPageClient datasetId={id} />
    </main>
  );
}
