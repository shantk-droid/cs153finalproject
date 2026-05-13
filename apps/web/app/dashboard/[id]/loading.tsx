export default function Loading() {
  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8">
      <div className="space-y-2">
        <div className="h-3 w-24 animate-pulse rounded bg-muted" />
        <div className="h-9 w-72 animate-pulse rounded bg-muted" />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-lg border bg-muted/40" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="h-[60vh] animate-pulse rounded-lg border bg-muted/40" />
        <div className="space-y-4">
          <div className="h-32 animate-pulse rounded-lg border bg-muted/40" />
          <div className="h-32 animate-pulse rounded-lg border bg-muted/40" />
          <div className="h-64 animate-pulse rounded-lg border bg-muted/40" />
        </div>
      </div>
    </main>
  );
}
