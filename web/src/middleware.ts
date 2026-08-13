import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIE_NAME } from "./lib/constants";

export function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const token = req.cookies.get(AUTH_COOKIE_NAME)?.value;

  const isAuthPage = path === "/login" || path === "/setup";
  const isProtectedPage =
    path === "/" ||
    path.startsWith("/dashboard") ||
    path.startsWith("/processes") ||
    path.startsWith("/tunnels") ||
    path.startsWith("/settings");

  if (isProtectedPage && !token) {
    return NextResponse.redirect(new URL("/login", req.url));
  }

  if (isAuthPage && token) {
    return NextResponse.redirect(new URL("/dashboard", req.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/",
    "/dashboard/:path*",
    "/processes/:path*",
    "/tunnels/:path*",
    "/settings/:path*",
    "/login",
    "/setup",
  ],
};
