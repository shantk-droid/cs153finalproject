// Lightweight Sentry init for the browser. Skips entirely when NEXT_PUBLIC_SENTRY_DSN is unset.
// Wrap heavy/Edge code paths in try/catch and call captureException(...) on errors.
//
// We deliberately do NOT pull in @sentry/nextjs as a hard dep — keeps bundle small and lets
// the project ship without an account. To enable, install @sentry/nextjs and replace this
// file's contents with `export { Sentry as default } from "@sentry/nextjs";`.

type ErrorLike = Error | string | unknown;

let initialized = false;
let sdk: { captureException?: (e: unknown) => void } | null = null;

export async function initSentry(): Promise<void> {
  if (initialized) return;
  initialized = true;
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  if (!dsn) return;
  try {
    // Optional dependency — only load if @sentry/browser is installed.
    // Hide the module specifier from TS so this typechecks even when the package is absent.
    const dynamicImport = new Function("s", "return import(s)") as (s: string) => Promise<unknown>;
    const mod = (await dynamicImport("@sentry/browser").catch(() => null)) as
      | { init: (opts: { dsn: string; tracesSampleRate?: number }) => void; captureException: (e: unknown) => void }
      | null;
    if (!mod) return;
    mod.init({ dsn, tracesSampleRate: 0.1 });
    sdk = mod;
  } catch {
    // Silent fail: Sentry is optional.
  }
}

export function captureException(err: ErrorLike): void {
  if (sdk?.captureException) {
    try {
      sdk.captureException(err);
    } catch {
      // ignore
    }
  }
}
