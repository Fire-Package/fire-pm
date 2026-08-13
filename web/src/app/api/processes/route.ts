import { NextRequest } from "next/server";
import { getAuthSession, errorResponse, successResponse } from "@/lib/api-helper";
import { ProcessService } from "@/lib/services/process.service";

export async function GET(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  try {
    const list = await ProcessService.list();
    return successResponse(list);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to fetch process list", 500);
  }
}
