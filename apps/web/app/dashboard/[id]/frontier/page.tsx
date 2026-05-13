import { FrontierPageClient } from "@/components/FrontierPageClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function FrontierPage({ params }: Props) {
  const { id } = await params;
  return (
    <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Inventory math</p>
        <h1 className="text-2xl font-semibold tracking-tight">Service-level vs cost frontier</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose your service level, see expected total cost. Newsvendor for single-period decisions.
        </p>
      </header>
      <FrontierPageClient datasetId={id} />
    </main>
  );
}
