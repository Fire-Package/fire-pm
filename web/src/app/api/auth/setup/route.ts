import { NextRequest, NextResponse } from "next/server";
import { AuthService } from "@/lib/services/auth.service";
import { AUTH_COOKIE_NAME, CSRF_COOKIE_NAME } from "@/lib/auth";
import { errorResponse } from "@/lib/api-helper";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { password } = body;

    const { token, csrfToken } = await AuthService.setup(password);

    const res = NextResponse.json({ ok: true });
    res.cookies.set(AUTH_COOKIE_NAME, token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: 60 * 60 * 24, // 24 hours
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
    return errorResponse(error.message || "Failed to complete setup", 400);
  }
}
