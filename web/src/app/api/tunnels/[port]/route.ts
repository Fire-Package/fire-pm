import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { TunnelService } from "@/lib/services/tunnel.service";

export async function DELETE(
  req: NextRequest,
  props: { params: Promise<{ port: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const portNum = parseInt(params.port, 10);
    const res = await TunnelService.close(portNum);
    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to close tunnel", 500);
  }
}
