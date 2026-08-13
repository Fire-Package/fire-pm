import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { ProcessService } from "@/lib/services/process.service";

export async function PUT(
  req: NextRequest,
  props: { params: Promise<{ name: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const body = await req.json();
    const { memory, cpu } = body;
    const res = await ProcessService.setLimits(params.name, memory, cpu);
    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to update resource limits", 400);
  }
}
