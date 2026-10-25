import { BACKEND_DOWN, backendFetch, jsonError } from "@/lib/backend";

export const dynamic = "force-dynamic";

/** Reicht den Strom der Live-Vorführung (Bilder und Meldungen) ohne Pufferung weiter; endet das Backend, endet er leise. */
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
      return reader.cancel(reason).catch(() => {});
    },
  });
}

export async function GET(request: Request) {
  const session = new URL(request.url).searchParams.get("session") ?? "";
  if (!/^[0-9a-f]{32}$/.test(session)) return jsonError("Unbekannte Sitzung", 400);
  try {
    const upstream = await backendFetch(`/api/flow/live/stream?session=${session}`, {
      headers: { accept: "text/event-stream" },
      signal: request.signal,
    });
    if (!upstream.ok || !upstream.body)
      return jsonError(
        upstream.status === 410 ? "Der Browser wurde inzwischen geschlossen – bitte neu starten." : BACKEND_DOWN,
        upstream.status === 410 ? 410 : 502,
      );
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
