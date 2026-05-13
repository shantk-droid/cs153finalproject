import { StressTestClient } from "@/components/StressTestClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function StressPage({ params }: Props) {
  const { id } = await params;
  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Risk</p>
        <h1 className="text-2xl font-semibold tracking-tight">Stress test</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Shock the inputs, recompute exposure. Lead-time disruption × demand surge × service-level target.
        </p>
      </header>
      <StressTestClient datasetId={id} />
    </main>
  );
}
