import { NextRequest } from "next/server";
import { getAuthSession, errorResponse, successResponse } from "@/lib/api-helper";
import { LogService } from "@/lib/services/log.service";

export async function GET(
  req: NextRequest,
  props: { params: Promise<{ name: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  const linesParam = req.nextUrl.searchParams.get("lines");
  const lines = linesParam ? parseInt(linesParam, 10) : 100;

  try {
    const history = await LogService.getHistory(params.name, lines);
    return successResponse({ lines: history, service: params.name });
  } catch (error: any) {
    return errorResponse(error.message || "Failed to fetch log history", 500);
  }
}
