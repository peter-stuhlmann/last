import { fetchModels, jsonError, readJson } from "@/lib/backend";
import { firstIssue, modelsRequestSchema } from "@/lib/validation";

export async function POST(request: Request) {
  const body = await readJson(request);
  if ("response" in body) return body.response;

  const parsed = modelsRequestSchema.safeParse(body.data);
  if (!parsed.success) return jsonError(firstIssue(parsed.error), 400);

  try {
    const models = await fetchModels(parsed.data.base_url, parsed.data.api_key);
    return Response.json({ models }, { headers: { "cache-control": "no-store" } });
  } catch {
    // Bewusst ohne Details: die Fehlermeldung könnte interne Namen oder Adressen verraten.
    return jsonError("Server nicht erreichbar oder keine Modellliste.", 502);
  }
}
