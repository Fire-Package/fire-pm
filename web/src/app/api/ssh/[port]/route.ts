import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { SshService } from "@/lib/services/ssh.service";

export async function DELETE(
  req: NextRequest,
  props: { params: Promise<{ port: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const target = params.port === "all" ? "all" : parseInt(params.port, 10);
    const res = await SshService.close(target);
    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to close SSH session", 500);
  }
}

export async function PATCH(
  req: NextRequest,
  props: { params: Promise<{ port: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const portNum = parseInt(params.port, 10);
    const body = await req.json();
    const title = typeof body.title === "string" ? body.title : "";
    const res = await SshService.setTitle(portNum, title);
    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to update SSH session title", 400);
  }
}
