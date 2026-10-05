import { BACKEND_DOWN, backendFetch, jsonError, passThrough } from "@/lib/backend";
import { isRunName } from "@/lib/security";

/** Vergleichsbericht (PowerPoint) aus zwei oder mehr Läufen. */
export async function GET(request: Request) {
  const names = (new URL(request.url).searchParams.get("runs") ?? "").split(",").filter(Boolean);
  if (names.length < 2 || names.length > 10 || !names.every(isRunName)) {
    return jsonError("Bitte mindestens zwei vorhandene Läufe wählen.", 400);
  }
  try {
    const upstream = await backendFetch(`/api/compare?runs=${encodeURIComponent(names.join(","))}`, {
      signal: AbortSignal.timeout(120_000),
    });
    if (upstream.status === 400) {
      // Eine 400 ist eine Auskunft für den Nutzer (z. B. „nur Läufe gleicher Art“), kein interner Fehler.
      const data = (await upstream.json().catch(() => ({}))) as { error?: unknown };
      return jsonError(typeof data.error === "string" ? data.error : "Vergleich nicht möglich.", 400);
    }
    if (!upstream.ok) return jsonError("Vergleich fehlgeschlagen.", 502);
    return passThrough(upstream);
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
