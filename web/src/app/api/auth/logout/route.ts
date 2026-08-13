import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIE_NAME, CSRF_COOKIE_NAME } from "@/lib/auth";

export async function POST(req: NextRequest) {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(AUTH_COOKIE_NAME);
  res.cookies.delete(CSRF_COOKIE_NAME);
  return res;
}
