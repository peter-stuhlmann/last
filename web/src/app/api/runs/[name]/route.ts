import { BACKEND_DOWN, backendFetch, jsonError } from "@/lib/backend";
import { isRunName } from "@/lib/security";

/** Lauf in den Papierkorb des Backends verschieben (results/.papierkorb, 7 Tage). */
export async function DELETE(_request: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  if (!isRunName(name)) return jsonError("Nicht gefunden.", 404);
  try {
    const res = await backendFetch(`/api/runs/${name}`, { method: "DELETE", signal: AbortSignal.timeout(10_000) });
    const data = (await res.json()) as Record<string, unknown>;
    if (!res.ok) return jsonError(typeof data.error === "string" ? data.error : "Löschen fehlgeschlagen.", res.status);
    return Response.json(data, { headers: { "cache-control": "no-store" } });
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
