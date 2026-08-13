import { NextRequest } from "next/server";
import { getAuthSession, errorResponse } from "@/lib/api-helper";
import { LogService } from "@/lib/services/log.service";

export async function GET(
  req: NextRequest,
  props: { params: Promise<{ name: string }> }
) {
  const params = await props.params;
  const session = getAuthSession(req);
  if (!session) return errorResponse("Unauthorized", 401, "UNAUTHORIZED");

  const encoder = new TextEncoder();
  let cleanup: (() => void) | null = null;

  const stream = new ReadableStream({
    start(controller) {
      // Send initial keepalive
      controller.enqueue(encoder.encode(": connected\n\n"));

      try {
        cleanup = LogService.streamLogs(
          params.name,
          (line: string) => {
            try {
              const data = JSON.stringify({ line });
              controller.enqueue(encoder.encode(`data: ${data}\n\n`));
            } catch {}
          },
          (err) => {
            try {
              controller.enqueue(encoder.encode(`data: ${JSON.stringify({ error: String(err) })}\n\n`));
            } catch {}
          }
        );
      } catch (err: any) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ error: err.message })}\n\n`));
        controller.close();
      }
    },
    cancel() {
      if (cleanup) {
        cleanup();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
