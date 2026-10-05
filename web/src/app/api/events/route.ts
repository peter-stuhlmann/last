import { BACKEND_DOWN, backendFetch, jsonError } from "@/lib/backend";

export const dynamic = "force-dynamic";

/**
 * Reicht den Strom des Backends weiter. Bricht das Backend mittendrin ab (Neustart, Absturz),
 * endet unser Strom einfach – ohne Fehler. Der Browser verbindet sich dann von selbst neu;
 * ein durchgereichter Fehler würde nur als „failed to pipe response“ im Protokoll landen.
 */
function relay(upstream: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const reader = upstream.getReader();
  return new ReadableStream({
    async pull(controller) {
      try {
        const { done, value } = await reader.read();
        if (done) controller.close();
        else controller.enqueue(value);
      } catch {
        controller.close();
      }
    },
    cancel(reason) {
      // Der Browser hat die Seite verlassen: auch die Verbindung zum Backend beenden.
      return reader.cancel(reason).catch(() => {});
    },
  });
}

/** Server-Sent Events des Backends ohne Pufferung durchreichen. */
export async function GET(request: Request) {
  try {
    const upstream = await backendFetch("/api/events", {
      headers: { accept: "text/event-stream" },
      signal: request.signal,
    });
    if (!upstream.ok || !upstream.body) return jsonError(BACKEND_DOWN, 502);
    return new Response(relay(upstream.body), {
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        "x-accel-buffering": "no",
        "x-content-type-options": "nosniff",
      },
    });
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
