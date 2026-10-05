// Reine Funktionen für proxy.ts und die Route Handler – ohne Abhängigkeiten, damit testbar.

export const DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"];

const RUN_NAME_RE = /^results_[\w-]{1,64}$/;

export function isRunName(name: unknown): name is string {
  return typeof name === "string" && RUN_NAME_RE.test(name);
}

export function allowedHostsFromEnv(value: string | undefined): string[] {
  const extra = (value ?? "")
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean);
  return [...DEFAULT_ALLOWED_HOSTS, ...extra];
}

function hostname(host: string): string {
  const h = host.trim().toLowerCase();
  // IPv6 in Klammern behält die Klammern, sonst wird der Port abgeschnitten
  return h.startsWith("[") ? h.slice(0, h.indexOf("]") + 1) : h.split(":")[0];
}

/** Schutz vor DNS-Rebinding: nur bekannte Host-Header bedienen. */
export function isAllowedHost(host: string | null | undefined, allowed: string[]): boolean {
  if (!host) return false;
  return allowed.includes(hostname(host));
}

interface RequestLike {
  method: string;
  path: string;
  headers: Headers;
}

/**
 * Prüft eine Anfrage. Gibt null zurück, wenn sie in Ordnung ist, sonst den HTTP-Status.
 * Die Oberfläche hat keinen Login – darum darf keine fremde Webseite im Browser
 * des Nutzers Tests starten, stoppen oder Ergebnisse lesen.
 */
export function checkRequest(req: RequestLike, allowedHosts: string[]): number | null {
  const host = req.headers.get("host");
  if (!isAllowedHost(host, allowedHosts)) return 421;
  if (!req.path.startsWith("/api/")) return null;

  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") return 403;

  const origin = req.headers.get("origin");
  if (origin) {
    let originHost: string;
    try {
      originHost = new URL(origin).host;
    } catch {
      return 403;
    }
    if (originHost.toLowerCase() !== host!.toLowerCase()) return 403;
  }

  const mutating = !["GET", "HEAD", "OPTIONS"].includes(req.method.toUpperCase());
  if (mutating) {
    // Ohne Origin und ohne Fetch-Metadaten kommt die Anfrage nicht aus einem aktuellen Browser
    // (z. B. curl) – das ist erlaubt, ein Cross-Site-Formular wäre es nicht.
    const type = req.headers.get("content-type") ?? "";
    if (!type.toLowerCase().startsWith("application/json")) return 415;
  }
  return null;
}

export function buildCsp(nonce: string, isDev: boolean): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // Im Dev-Modus fügt Next Styles ohne Nonce ein (Fehler-Overlay, HMR)
    isDev ? "style-src 'self' 'unsafe-inline'" : `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}
