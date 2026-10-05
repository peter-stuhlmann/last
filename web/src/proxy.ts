import { NextResponse, type NextRequest } from "next/server";
import { allowedHostsFromEnv, buildCsp, checkRequest } from "@/lib/security";

const MESSAGES: Record<number, string> = {
  403: "Anfrage von fremder Seite abgelehnt.",
  415: "Content-Type muss application/json sein.",
  421: "Unbekannter Host. Erlaubte Namen stehen in ALLOWED_HOSTS.",
};

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const denied = checkRequest(
    { method: request.method, path: pathname, headers: request.headers },
    allowedHostsFromEnv(process.env.ALLOWED_HOSTS),
  );
  if (denied) {
    return NextResponse.json({ error: MESSAGES[denied] }, { status: denied, headers: { "cache-control": "no-store" } });
  }
  if (pathname.startsWith("/api/")) return NextResponse.next();

  // Seiten bekommen pro Aufruf eine frische Nonce für die Content Security Policy.
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildCsp(nonce, process.env.NODE_ENV === "development");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico|icon.svg).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
