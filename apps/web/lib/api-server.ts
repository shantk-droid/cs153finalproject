// Server-side API helper. Calls Modal directly via MODAL_API_URL.
//
// Why this exists: when SSR pages did `fetch(${proto}://${host}/api/...)` to
// loop through their own /api proxy on Vercel, the self-fetch returned 404 and
// every dashboard page rendered Next's notFound(). Calling Modal directly from
// the server bypasses the loop. The /api proxy is still used for browser-side
// calls (LandingActions, client components).

const API_BASE = (
  process.env.MODAL_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/+$/, "");

export async function serverFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T | null> {
  try {
    const r = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}
