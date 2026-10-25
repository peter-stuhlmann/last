import { describe, expect, it } from "vitest";
import { buildCsp, checkRequest, isAllowedHost, isRunName } from "./security";

const allowed = ["localhost", "127.0.0.1", "[::1]"];

describe("isAllowedHost", () => {
  it("lässt nur bekannte Rechnernamen zu – mit beliebigem Port", () => {
    expect(isAllowedHost("localhost:8090", allowed)).toBe(true);
    expect(isAllowedHost("127.0.0.1", allowed)).toBe(true);
    expect(isAllowedHost("[::1]:3000", allowed)).toBe(true);
    expect(isAllowedHost("LOCALHOST:3000", allowed)).toBe(true);
  });
  it("blockt fremde Namen (Schutz vor DNS-Rebinding)", () => {
    expect(isAllowedHost("evil.example:8090", allowed)).toBe(false);
    expect(isAllowedHost("localhost.evil.example", allowed)).toBe(false);
    expect(isAllowedHost("", allowed)).toBe(false);
    expect(isAllowedHost(null, allowed)).toBe(false);
  });
});

function req(method: string, path: string, headers: Record<string, string>) {
  return { method, path, headers: new Headers(headers) };
}

describe("checkRequest", () => {
  it("erlaubt normale Seitenaufrufe", () => {
    expect(checkRequest(req("GET", "/", { host: "localhost:8090" }), allowed)).toBeNull();
  });
  it("lehnt einen fremden Host ab", () => {
    expect(checkRequest(req("GET", "/", { host: "evil.example" }), allowed)).toBe(421);
  });
  it("lehnt schreibende Anfragen von fremden Seiten ab (CSRF)", () => {
    const base = { host: "localhost:8090", "content-type": "application/json" };
    expect(checkRequest(req("POST", "/api/start", { ...base, origin: "https://evil.example" }), allowed)).toBe(403);
    expect(checkRequest(req("POST", "/api/start", { ...base, "sec-fetch-site": "cross-site" }), allowed)).toBe(403);
    expect(
      checkRequest(req("POST", "/api/start", { ...base, origin: "http://localhost:8090", "sec-fetch-site": "same-origin" }), allowed),
    ).toBeNull();
  });
  it("verlangt JSON bei schreibenden Anfragen (kein „einfaches“ Formular-POST)", () => {
    expect(
      checkRequest(req("POST", "/api/start", { host: "localhost", origin: "http://localhost", "content-type": "text/plain" }), allowed),
    ).toBe(415);
  });
  it("lässt fremde Seiten auch keine API-Daten lesen oder Downloads auslösen", () => {
    expect(checkRequest(req("GET", "/api/events", { host: "localhost", "sec-fetch-site": "cross-site" }), allowed)).toBe(403);
    // Direktaufruf in der Adresszeile bleibt möglich
    expect(checkRequest(req("GET", "/api/runs/x/report.pdf", { host: "localhost", "sec-fetch-site": "none" }), allowed)).toBeNull();
  });
});

describe("isRunName", () => {
  it("akzeptiert nur Ordnernamen von Läufen", () => {
    expect(isRunName("results_20261004_234100")).toBe(true);
    expect(isRunName("results_../../etc")).toBe(false);
    expect(isRunName("../results_1")).toBe(false);
    expect(isRunName("results_" + "a".repeat(80))).toBe(false);
    expect(isRunName(undefined)).toBe(false);
  });
});

describe("buildCsp", () => {
  it("erlaubt Skripte nur mit Nonce und verbietet Einbettung", () => {
    const csp = buildCsp("abc", false);
    expect(csp).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
  });
  it("erlaubt eval nur in der Entwicklung", () => {
    expect(buildCsp("abc", true)).toContain("'unsafe-eval'");
  });
});
