import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { ProcessService } from "@/lib/services/process.service";

export async function POST(
  req: NextRequest,
  props: { params: Promise<{ name: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const res = await ProcessService.start(params.name);
    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to start process", 500);
  }
}
