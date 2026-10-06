import { BACKEND_DOWN, backendFetch, jsonError, readJson } from "@/lib/backend";
import { isRunName } from "@/lib/security";
import { firstIssue, notesSchema } from "@/lib/validation";

/** Titel, Tags, Notiz und Pin eines Laufs speichern – geprüft, dann ans Backend. */
export async function PUT(request: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  if (!isRunName(name)) return jsonError("Nicht gefunden.", 404);
  const body = await readJson(request);
  if ("response" in body) return body.response;
  const parsed = notesSchema.safeParse(body.data);
  if (!parsed.success) return jsonError(firstIssue(parsed.error), 400);
  try {
    const res = await backendFetch(`/api/runs/${name}/notes`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(parsed.data),
      signal: AbortSignal.timeout(10_000),
    });
    const data = (await res.json()) as Record<string, unknown>;
    if (!res.ok) return jsonError(typeof data.error === "string" ? data.error : "Speichern fehlgeschlagen.", res.status);
    return Response.json(data, { headers: { "cache-control": "no-store" } });
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
