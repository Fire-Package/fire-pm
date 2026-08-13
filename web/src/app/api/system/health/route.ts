import { NextRequest } from "next/server";
import { getAuthSession, errorResponse, successResponse } from "@/lib/api-helper";
import { SystemService } from "@/lib/services/system.service";

export async function GET(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  try {
    const health = await SystemService.getHealth();
    return successResponse(health);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to fetch system health", 500);
  }
}
