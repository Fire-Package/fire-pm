import { NextRequest, NextResponse } from "next/server";
import { verifyJwtToken, AUTH_COOKIE_NAME, CSRF_COOKIE_NAME } from "./auth";

export interface AuthContext {
  sub: string;
  role: string;
}

export function getAuthSession(req: NextRequest): AuthContext | null {
  const token = req.cookies.get(AUTH_COOKIE_NAME)?.value;
  if (!token) return null;
  const payload = verifyJwtToken(token);
  if (!payload) return null;
  return { sub: payload.sub, role: payload.role };
}

export function verifyCsrf(req: NextRequest): boolean {
  // Only verify on mutating methods
  if (["GET", "HEAD", "OPTIONS"].includes(req.method)) return true;

  const headerCsrf = req.headers.get("x-csrf-token");
  const cookieCsrf = req.cookies.get(CSRF_COOKIE_NAME)?.value;

  if (!headerCsrf || !cookieCsrf) return false;
  return headerCsrf === cookieCsrf;
}

export function errorResponse(message: string, status: number = 400, code: string = "BAD_REQUEST") {
  return NextResponse.json(
    { error: { code, message } },
    { status }
  );
}

export function successResponse(data: any, status: number = 200) {
  return NextResponse.json(data, { status });
}
