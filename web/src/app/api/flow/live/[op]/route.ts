import { BACKEND_DOWN, backendFetch, jsonError, readJson } from "@/lib/backend";
import { cleanLiveReply } from "@/lib/live";
import { firstIssue, liveActSchema, liveInputSchema, liveLookSchema, liveStartSchema } from "@/lib/validation";

// Das Backend bricht nach 150 s selbst ab (eine lange Chat-Antwort); etwas Luft für den Start des Browsers
const TIMEOUT_MS = 170_000;

/** Vorführen eines Ablaufs: start öffnet den Browser, act führt einen Klick oder eine Eingabe aus, stop schließt ihn. */
export async function POST(request: Request, { params }: { params: Promise<{ op: string }> }) {
  const { op } = await params;
  if (op !== "start" && op !== "act" && op !== "look" && op !== "stop" && op !== "input") return jsonError("Nicht gefunden.", 404);

  let payload: unknown = {};
  if (op !== "stop") {
    const body = await readJson(request);
    if ("response" in body) return body.response;
    const schema = op === "start" ? liveStartSchema : op === "look" ? liveLookSchema : op === "input" ? liveInputSchema : liveActSchema;
    const parsed = schema.safeParse(body.data);
    if (!parsed.success) return jsonError(firstIssue(parsed.error), 400);
    payload = parsed.data;
  }

  try {
    const res = await backendFetch(`/api/flow/live/${op}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const data = (await res.json()) as Record<string, unknown>;
    if (!res.ok) return jsonError(typeof data.error === "string" ? data.error : "Vorführen fehlgeschlagen.", res.status);
    return Response.json(op === "stop" || op === "input" ? { ok: true } : cleanLiveReply(data), {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
