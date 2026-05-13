"use client";

import Link from "next/link";

export default function SkuDetailError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-start justify-center gap-4 px-6">
      <p className="text-xs uppercase tracking-widest text-destructive">SKU detail error</p>
      <h1 className="text-2xl font-semibold tracking-tight">Couldn't load this SKU</h1>
      <p className="text-sm text-muted-foreground">{error.message || "An unexpected error occurred."}</p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={reset}
          className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
        >
          Retry
        </button>
      </div>
    </main>
  );
}
