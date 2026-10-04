import { NextRequest } from "next/server";
import { getAuthSession, verifyCsrf, errorResponse, successResponse } from "@/lib/api-helper";
import { SshService } from "@/lib/services/ssh.service";

export async function GET(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  try {
    const list = await SshService.list();
    return successResponse(list);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to list SSH sessions", 500);
  }
}

export async function POST(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!verifyCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const body = await req.json();
    const { port, title, password, provider, noTunnel } = body;
    const res = await SshService.create({
      port: port ? Number(port) : undefined,
      title: title ? String(title) : undefined,
      password: password ? String(password) : undefined,
      provider: provider ? String(provider) : undefined,
      noTunnel: Boolean(noTunnel),
    });
    return successResponse(res, 201);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to create SSH session", 400);
  }
}
