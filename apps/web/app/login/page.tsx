"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginSkeleton />}>
      <LoginInner />
    </Suspense>
  );
}

function LoginSkeleton() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center justify-center px-6">
      <p className="text-sm text-muted-foreground">Loading…</p>
    </main>
  );
}

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const from = params.get("from") || "/";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const r = await fetch("/login/submit", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!r.ok) {
        const body = await r.text();
        setError(body || `Login failed (${r.status})`);
        return;
      }
      router.replace(from);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-6">
      <header className="space-y-1">
        <p className="text-xs uppercase tracking-widest text-muted-foreground">Inventory Optimizer</p>
        <h1 className="text-2xl font-semibold tracking-tight">Demo password required</h1>
        <p className="text-sm text-muted-foreground">Enter the shared demo password to continue.</p>
      </header>
      <form onSubmit={submit} className="space-y-3 rounded-lg border bg-card p-5">
        <input
          type="password"
          autoFocus
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
        />
        {error && <p className="text-sm text-destructive">{error}</p>}
        <button
          type="submit"
          disabled={pending || !password}
          className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary text-sm font-medium text-primary-foreground disabled:opacity-60"
        >
          {pending ? "Verifying…" : "Continue"}
        </button>
      </form>
    </main>
  );
}
