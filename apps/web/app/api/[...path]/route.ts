import { NextRequest, NextResponse } from "next/server";

// Server-side env var (NOT NEXT_PUBLIC_ — keeps the Modal URL off the client).
// Set in Vercel project settings → Environment Variables.
// Locally, set in apps/web/.env.local
const API_BASE = process.env.MODAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "te",
  "trailer",
  "proxy-authorization",
  "proxy-authenticate",
  "upgrade",
  "host",
  "content-length",
]);

function buildHeaders(req: NextRequest): Headers {
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });
  return headers;
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = new URL(`${API_BASE.replace(/\/+$/, "")}/${path.join("/")}`);
  req.nextUrl.searchParams.forEach((v, k) => target.searchParams.set(k, v));

  const init: RequestInit = {
    method: req.method,
    headers: buildHeaders(req),
    redirect: "manual",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target.toString(), init);
  } catch (err) {
    return NextResponse.json(
      { error: "upstream_unreachable", detail: String(err), target: target.toString() },
      { status: 502 },
    );
  }

  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) respHeaders.set(key, value);
  });

  // SSE endpoints (e.g. /chat) must stream straight through. For everything
  // else we buffer the full body server-side: piping `upstream.body` through
  // Vercel's serverless boundary occasionally truncates mid-stream, which
  // surfaces on the client as `status: 200` + `TypeError: Failed to fetch`
  // when r.json()/r.text() tries to read the (incomplete) body.
  const contentType = upstream.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    return new NextResponse(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: respHeaders,
    });
  }

  let buffer: ArrayBuffer;
  try {
    buffer = await upstream.arrayBuffer();
  } catch (err) {
    return NextResponse.json(
      { error: "upstream_body_truncated", detail: String(err), target: target.toString() },
      { status: 502 },
    );
  }
  return new NextResponse(buffer, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
