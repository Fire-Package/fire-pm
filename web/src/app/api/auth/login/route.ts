import { NextRequest, NextResponse } from "next/server";
import { AuthService } from "@/lib/services/auth.service";
import { AUTH_COOKIE_NAME, CSRF_COOKIE_NAME, checkRateLimit } from "@/lib/auth";
import { errorResponse } from "@/lib/api-helper";

export async function POST(req: NextRequest) {
  try {
    const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "127.0.0.1";
    const allowed = checkRateLimit(`login:${ip}`, 5, 60000);
    if (!allowed) {
      return errorResponse("Too many login attempts. Please wait 1 minute before trying again.", 429, "RATE_LIMITED");
    }

    const body = await req.json();
    const { password } = body;

    const { token, csrfToken } = await AuthService.login(password);

    const res = NextResponse.json({ ok: true });
    res.cookies.set(AUTH_COOKIE_NAME, token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: 60 * 60 * 24,
    });
    res.cookies.set(CSRF_COOKIE_NAME, csrfToken, {
      httpOnly: false,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: 60 * 60 * 24,
    });

    return res;
  } catch (error: any) {
    return errorResponse(error.message || "Invalid credentials", 401, "INVALID_CREDENTIALS");
  }
}
