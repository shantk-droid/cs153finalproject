"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, ClipboardCheck, Copy, Loader2, RefreshCw, Sparkles } from "lucide-react";

const TEMPLATES: Array<{ value: string; label: string; sub: string }> = [
  { value: "retail_stable", label: "Retail (stable weekly)", sub: "200 SKUs · 2 yrs · BEV/snacks/care" },
  { value: "coffee_perishable", label: "Coffee (perishable daily)", sub: "80 SKUs · 6 mo · short LT" },
  { value: "ecommerce_lumpy", label: "E-commerce (lumpy long-tail)", sub: "300 SKUs · 2 yrs · intermittent" },
];

const DEMO_TIMEOUT_MS = 90_000;

interface DemoError {
  message: string;
  status?: number;
  bodySnippet?: string;
  template: string;
  timestamp: string;
  userAgent: string;
}

async function pingApi(signal: AbortSignal): Promise<void> {
  // Hits the API health endpoint via the Vercel proxy. Used to wake a cold Modal
  // container as soon as the landing page mounts so the demo button feels instant.
  try {
    await fetch("/api/health", { method: "GET", signal });
  } catch {
    /* ignore — pre-warm is a nicety, not required */
  }
}

export function LandingActions() {
  const router = useRouter();
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<DemoError | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    pingApi(ctrl.signal);
    return () => ctrl.abort();
  }, []);

  async function loadDemo(template: string) {
    setError(null);
    setLoading(template);
    const ctrl = new AbortController();
    const timeoutId = setTimeout(() => ctrl.abort(), DEMO_TIMEOUT_MS);
    let status: number | undefined;
    let bodySnippet: string | undefined;
    try {
      const r = await fetch(`/api/datasets/demo/${template}`, {
        method: "POST",
        signal: ctrl.signal,
      });
      status = r.status;
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        bodySnippet = text.slice(0, 200);
        throw new Error(`API returned ${r.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
      }
      const summary = await r.json();
      router.push(`/dashboard/${summary.dataset_id}/overview`);
    } catch (e: unknown) {
      const aborted = (e as Error)?.name === "AbortError";
      const message = aborted
        ? "Demo took too long — the API may be cold-starting. Retry in a few seconds."
        : e instanceof TypeError && e.message === "Failed to fetch"
        ? "Couldn't reach the API. Check your connection or retry."
        : e instanceof Error
        ? e.message
        : "Failed to load demo";
      setError({
        message,
        status,
        bodySnippet,
        template,
        timestamp: new Date().toISOString(),
        userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "",
      });
      setLoading(null);
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async function copyDiagnostic() {
    if (!error) return;
    const blob = JSON.stringify(error, null, 2);
    try {
      await navigator.clipboard.writeText(blob);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard API unavailable — silently noop */
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/upload"
          className="group inline-flex h-11 items-center justify-center gap-2 rounded-md bg-gradient-to-r from-primary to-primary/85 px-6 text-sm font-medium text-primary-foreground shadow transition-all hover:shadow-lg hover:shadow-primary/25 dark:from-primary dark:to-primary/75"
        >
          Upload your data
          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
        </Link>
        <HealthBadge />
      </div>
      <div className="rounded-lg border bg-card p-4">
        <p className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="h-4 w-4 text-primary" />
          Or load a realistic demo dataset
        </p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          {TEMPLATES.map((t) => (
            <button
              key={t.value}
              type="button"
              disabled={loading !== null}
              onClick={() => loadDemo(t.value)}
              className="rounded-md border bg-background px-3 py-2 text-left text-sm transition-colors hover:bg-accent disabled:opacity-50"
            >
              <p className="font-medium">{t.label}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{t.sub}</p>
              {loading === t.value && (
                <p className="mt-1 inline-flex items-center gap-1 text-[11px] text-primary">
                  <Loader2 className="h-3 w-3 animate-spin" /> Generating dataset…
                </p>
              )}
            </button>
          ))}
        </div>
        {loading && (
          <p className="mt-2 text-[11px] text-muted-foreground">
            Generating ~20k rows + computing the data-quality report. Up to ~30 s on a cold start.
          </p>
        )}
        {error && (
          <div className="mt-3 flex flex-col gap-2 rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
            <p className="font-medium">{error.message}</p>
            {error.status !== undefined && (
              <p className="text-[11px] opacity-80">
                HTTP {error.status}
                {error.bodySnippet ? ` · ${error.bodySnippet}` : ""}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                type="button"
                onClick={() => loadDemo(error.template)}
                className="inline-flex items-center gap-1 rounded-md border border-red-300 bg-white px-2 py-1 text-[11px] font-medium text-red-700 hover:bg-red-50 dark:border-red-900/60 dark:bg-transparent dark:text-red-300"
              >
                <RefreshCw className="h-3 w-3" /> Retry
              </button>
              <button
                type="button"
                onClick={copyDiagnostic}
                className="inline-flex items-center gap-1 rounded-md border border-red-300 bg-white px-2 py-1 text-[11px] font-medium text-red-700 hover:bg-red-50 dark:border-red-900/60 dark:bg-transparent dark:text-red-300"
              >
                {copied ? (
                  <>
                    <ClipboardCheck className="h-3 w-3" /> Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3 w-3" /> Copy diagnostic
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function HealthBadge() {
  const [state, setState] = useState<"loading" | "ok" | "err">("loading");
  const [detail, setDetail] = useState<string>("");

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/health", { signal: ctrl.signal })
      .then(async (r) => {
        if (r.ok) {
          setState("ok");
        } else {
          setState("err");
          setDetail(`HTTP ${r.status}`);
        }
      })
      .catch((e) => {
        if ((e as Error)?.name === "AbortError") return;
        setState("err");
        setDetail(String(e));
      });
    return () => ctrl.abort();
  }, []);

  const dot =
    state === "ok"
      ? "bg-emerald-500"
      : state === "err"
      ? "bg-red-500"
      : "bg-muted-foreground/40 animate-pulse";
  const label = state === "ok" ? "API ready" : state === "err" ? "API unreachable" : "Checking API…";

  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
      title={detail || label}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
