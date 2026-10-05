import { BACKEND_DOWN, backendFetch, jsonError, readJson } from "@/lib/backend";
import { firstIssue, startSchema } from "@/lib/validation";

export async function POST(request: Request) {
  const body = await readJson(request);
  if ("response" in body) return body.response;

  const parsed = startSchema.safeParse(body.data);
  if (!parsed.success) return jsonError(firstIssue(parsed.error), 400);

  try {
    const res = await backendFetch("/api/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(parsed.data),
      signal: AbortSignal.timeout(10_000),
    });
    const data = (await res.json()) as { run?: unknown; error?: unknown };
    if (!res.ok) return jsonError(typeof data.error === "string" ? data.error : "Start fehlgeschlagen.", res.status);
    return Response.json({ ok: true, run: String(data.run ?? "") }, { headers: { "cache-control": "no-store" } });
  } catch {
    return jsonError(BACKEND_DOWN, 502);
  }
}
