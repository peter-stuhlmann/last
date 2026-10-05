// Für den Docker-Healthcheck: antwortet, sobald der Next-Server läuft.
export function GET() {
  return Response.json({ ok: true }, { headers: { "cache-control": "no-store" } });
}
