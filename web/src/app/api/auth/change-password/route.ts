import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { AuthService } from "@/lib/services/auth.service";

export async function POST(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const body = await req.json();
    const { currentPassword, newPassword } = body;
    if (!currentPassword || !newPassword) {
      return errorResponse("Current and new passwords are required");
    }

    await AuthService.changePassword(currentPassword, newPassword);
    return successResponse({ ok: true, message: "Password updated successfully" });
  } catch (error: any) {
    return errorResponse(error.message || "Failed to change password", 400);
  }
}
