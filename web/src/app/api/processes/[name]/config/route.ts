import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { ConfigService } from "@/lib/services/config.service";

export async function GET(
  req: NextRequest,
  props: { params: Promise<{ name: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  try {
    const content = await ConfigService.getUnitContent(params.name);
    return successResponse({ content });
  } catch (error: any) {
    return errorResponse(error.message || "Failed to load unit file", 500);
  }
}

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
    const { content } = body;
    const res = await ConfigService.updateUnitContent(params.name, content);
    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to update unit file", 400);
  }
}
