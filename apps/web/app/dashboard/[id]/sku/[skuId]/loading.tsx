export default function Loading() {
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <div className="space-y-2">
        <div className="h-3 w-20 animate-pulse rounded bg-muted" />
        <div className="h-7 w-48 animate-pulse rounded bg-muted" />
      </div>
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="h-[420px] animate-pulse rounded-lg border bg-muted/40" />
        <div className="space-y-4">
          <div className="h-72 animate-pulse rounded-lg border bg-muted/40" />
          <div className="h-48 animate-pulse rounded-lg border bg-muted/40" />
        </div>
      </div>
    </main>
  );
}
