import Link from "next/link";

export default function DashboardLanding() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6">
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Dashboard</p>
        <h1 className="text-3xl font-semibold tracking-tight">No dataset loaded</h1>
        <p className="text-muted-foreground">
          Upload a CSV or Excel file to see the dashboard. After upload + confirm, you'll be sent
          to the per-dataset view at <code className="font-mono text-xs">/dashboard/[id]</code>.
        </p>
      </header>
      <div className="flex gap-3">
        <Link
          href="/upload"
          className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Upload data →
        </Link>
      </div>
    </main>
  );
}
