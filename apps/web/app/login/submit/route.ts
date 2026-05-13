import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  const expected = process.env.DEMO_PASSWORD;
  if (!expected) {
    return new NextResponse("DEMO_PASSWORD not configured", { status: 500 });
  }
  let body: { password?: string };
  try {
    body = (await req.json()) as { password?: string };
  } catch {
    return new NextResponse("invalid JSON", { status: 400 });
  }
  if (!body.password) {
    return new NextResponse("password required", { status: 400 });
  }
  if (body.password !== expected) {
    return new NextResponse("incorrect password", { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set("demo_auth", "ok", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });
  return res;
}
