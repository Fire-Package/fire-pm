import { NextRequest, NextResponse } from "next/server";
import { getAuthSession } from "@/lib/api-helper";
import { AuthService } from "@/lib/services/auth.service";

export async function GET(req: NextRequest) {
  const isConfigured = AuthService.isConfigured();
  if (!isConfigured) {
    return NextResponse.json({ authenticated: false, isConfigured: false });
  }

  const session = getAuthSession(req);
  if (!session) {
    return NextResponse.json({ authenticated: false, isConfigured: true });
  }

  return NextResponse.json({
    authenticated: true,
    isConfigured: true,
    user: {
      username: session.sub,
      role: session.role,
    },
  });
}
