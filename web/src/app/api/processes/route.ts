import { NextRequest } from "next/server";
import { getAuthSession, errorResponse, successResponse, validateCsrf } from "@/lib/api-helper";
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

export async function POST(req: NextRequest) {
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");
  if (!validateCsrf(req)) return errorResponse("Invalid CSRF token", 403, "CSRF_ERROR");

  try {
    const body = await req.json();
    if (!body.script || typeof body.script !== "string") {
      return errorResponse("Script file path is required", 400);
    }

    const res = await ProcessService.create({
      script: body.script.trim(),
      name: body.name ? body.name.trim() : undefined,
      interpreter: body.interpreter ? body.interpreter.trim() : undefined,
      env: Array.isArray(body.env) ? body.env : undefined,
      watch: Boolean(body.watch),
      reload: Boolean(body.reload),
      mem: body.mem ? body.mem.trim() : undefined,
      cpu: body.cpu ? body.cpu.trim() : undefined,
    });

    return successResponse(res);
  } catch (error: any) {
    return errorResponse(error.message || "Failed to start process", 500);
  }
}
