import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIE_NAME } from "./lib/constants";

const INSECURE_SECRETS = new Set([
  "default-secret",
  "secret",
  "changeme",
  "123456",
  "admin",
]);

function base64UrlToArrayBuffer(input: string): ArrayBuffer {
  const padded = input.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (input.length % 4)) % 4);
  const binary = atob(padded);
  const buf = new ArrayBuffer(binary.length);
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return buf;
}

async function isEdgeTokenPlausible(token: string): Promise<boolean> {
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  try {
    const payloadBytes = base64UrlToArrayBuffer(parts[1]);
    const payload = JSON.parse(new TextDecoder().decode(payloadBytes));
    if (!payload || typeof payload !== "object") return false;
    if (typeof payload.exp !== "number" || payload.exp * 1000 <= Date.now()) {
      return false;
    }

    const envSecret = process.env.JWT_SECRET?.trim();
    if (envSecret && envSecret.length >= 16 && !INSECURE_SECRETS.has(envSecret.toLowerCase())) {
      const key = await crypto.subtle.importKey(
        "raw",
        new TextEncoder().encode(envSecret),
        { name: "HMAC", hash: "SHA-256" },
        false,
        ["verify"]
      );
      const signingInput = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
      const sigBuf = base64UrlToArrayBuffer(parts[2]);
      return await crypto.subtle.verify("HMAC", key, sigBuf, signingInput);
    }

    return true;
  } catch {
    return false;
  }
}

export async function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const token = req.cookies.get(AUTH_COOKIE_NAME)?.value;

  const isAuthPage = path === "/login" || path === "/setup";
  const isProtectedPage =
    path === "/" ||
    path.startsWith("/dashboard") ||
    path.startsWith("/processes") ||
    path.startsWith("/tunnels") ||
    path.startsWith("/ssh") ||
    path.startsWith("/settings");

  const hasValidToken = token ? await isEdgeTokenPlausible(token) : false;

  if (isProtectedPage && !hasValidToken) {
    const res = NextResponse.redirect(new URL("/login", req.url));
    if (token) res.cookies.delete(AUTH_COOKIE_NAME);
    return res;
  }

  if (isAuthPage && hasValidToken) {
    return NextResponse.redirect(new URL("/dashboard", req.url));
  }

  if (isAuthPage && token && !hasValidToken) {
    const res = NextResponse.next();
    res.cookies.delete(AUTH_COOKIE_NAME);
    return res;
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/",
    "/dashboard/:path*",
    "/processes/:path*",
    "/tunnels/:path*",
    "/ssh/:path*",
    "/settings/:path*",
    "/login",
    "/setup",
  ],
};
