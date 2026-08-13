import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { ProcessService } from "@/lib/services/process.service";

export async function GET(
  req: NextRequest,
  props: { params: Promise<{ name: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  try {
    const detail = await ProcessService.getDetail(params.name);
    if (!detail) {
      return errorResponse(`Process '${params.name}' not found`, 404, "NOT_FOUND");
    }
    return successResponse(detail);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to get process details", 500);
  }
}

export async function DELETE(
  req: NextRequest,
  props: { params: Promise<{ name: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const res = await ProcessService.delete(params.name);
    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to delete process", 500);
  }
}
