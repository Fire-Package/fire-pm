import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { TunnelService } from "@/lib/services/tunnel.service";

export async function GET(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  try {
    const list = await TunnelService.list();
    return successResponse(list);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to list tunnels", 500);
  }
}

export async function POST(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const body = await req.json();
    const { port, provider } = body;
    const res = await TunnelService.open(Number(port), provider);
    return successResponse(res, 201);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to open tunnel", 400);
  }
}
