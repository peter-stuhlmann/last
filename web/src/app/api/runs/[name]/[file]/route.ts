import { BACKEND_DOWN, backendFetch, jsonError, passThrough } from "@/lib/backend";
import { isRunName } from "@/lib/security";

const FILES = new Set(["report.pptx", "report.pdf", "raw_requests.jsonl", "summary.json"]);
// Bildschirmfotos der Ablauf-Aufzeichnung: schritt_01.png … schritt_99.png, schritt_fehler.png
const SCREENSHOT = /^schritt_(\d\d|fehler)\.png$/;

export async function GET(_request: Request, { params }: { params: Promise<{ name: string; file: string }> }) {
  const { name, file } = await params;
  if (!isRunName(name) || !(FILES.has(file) || SCREENSHOT.test(file))) return jsonError("Nicht gefunden.", 404);
  try {
    const upstream = await backendFetch(`/api/runs/${name}/${file}`, { signal: AbortSignal.timeout(30_000) });
    if (!upstream.ok) return jsonError("Nicht gefunden.", 404);
    return passThrough(upstream);
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
