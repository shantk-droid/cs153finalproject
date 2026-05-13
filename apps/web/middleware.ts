import { NextRequest, NextResponse } from "next/server";

// Single shared-password gate. Set DEMO_PASSWORD in env to enable; leave blank to disable.
// Cookie `demo_auth=ok` is set on /login submit; everything else redirects to /login when gate is on.

const COOKIE_NAME = "demo_auth";
const COOKIE_VALUE = "ok";

const PUBLIC_PATHS = new Set<string>([
  "/login",
  "/api/login",
  "/favicon.ico",
  "/_next",
  "/api",
]);

export function middleware(req: NextRequest) {
  const password = process.env.DEMO_PASSWORD;
  if (!password) {
    return NextResponse.next();
  }

  const { pathname } = req.nextUrl;
  // Allow Next.js internals + API proxy + login
  if (
    pathname === "/login" ||
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/api/") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  const cookie = req.cookies.get(COOKIE_NAME);
  if (cookie?.value === COOKIE_VALUE) {
    return NextResponse.next();
  }

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("from", pathname);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
