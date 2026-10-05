import { BACKEND_DOWN, backendFetch, jsonError } from "@/lib/backend";

export async function POST() {
  try {
    await backendFetch("/api/stop", { method: "POST", signal: AbortSignal.timeout(10_000) });
    return Response.json({ ok: true }, { headers: { "cache-control": "no-store" } });
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
