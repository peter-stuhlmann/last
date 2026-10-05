import { describe, expect, it } from "vitest";
import { modelsRequestSchema, parseBaseUrl, parseHeaderLines, startSchema } from "./validation";

describe("parseBaseUrl", () => {
  it("akzeptiert http(s)-Adressen und entfernt den Schrägstrich am Ende", () => {
    expect(parseBaseUrl(" https://ailaitie.p.tnurl.de/v1/ ")).toBe("https://ailaitie.p.tnurl.de/v1");
    expect(parseBaseUrl("http://spark.buero.lan:8000/v1")).toBe("http://spark.buero.lan:8000/v1");
  });
  it("lehnt andere Protokolle, Zugangsdaten und Unsinn ab", () => {
    expect(parseBaseUrl("file:///etc/passwd")).toBeNull();
    expect(parseBaseUrl("javascript:alert(1)")).toBeNull();
    expect(parseBaseUrl("http://user:pass@host/v1")).toBeNull();
    expect(parseBaseUrl("spark.buero.lan")).toBeNull();
    expect(parseBaseUrl("")).toBeNull();
    expect(parseBaseUrl("http://" + "a".repeat(3000))).toBeNull();
  });
});

describe("startSchema", () => {
  const ok = { base_url: "http://spark.buero.lan:8000/v1", slo_ttft: 2, slo_user_tps: 10, target_users: 80 };

  it("nimmt eine gültige Anfrage an", () => {
    const r = startSchema.safeParse({ ...ok, levels: "1,4,16,32,64", tests: "baseline,ramp" });
    expect(r.success).toBe(true);
  });
  it("wirft unbekannte Felder weg (z. B. den Ausgabeordner)", () => {
    const r = startSchema.parse({ ...ok, out: "/etc", report_only: "x", compare: "y" });
    expect(r).not.toHaveProperty("out");
    expect(r).not.toHaveProperty("report_only");
    expect(r).not.toHaveProperty("compare");
  });
  it("lehnt ungültige Adressen und Werte außerhalb der Grenzen ab", () => {
    expect(startSchema.safeParse({ ...ok, base_url: "ftp://x" }).success).toBe(false);
    expect(startSchema.safeParse({ ...ok, slo_ttft: -1 }).success).toBe(false);
    expect(startSchema.safeParse({ ...ok, target_users: 1e9 }).success).toBe(false);
    expect(startSchema.safeParse({ ...ok, levels: "1,2;rm -rf" }).success).toBe(false);
    expect(startSchema.safeParse({ ...ok, levels: "1,99999" }).success).toBe(false);
    expect(startSchema.safeParse({ ...ok, tests: "baseline,evil" }).success).toBe(false);
    expect(startSchema.safeParse({ ...ok, soak_minutes: 100000 }).success).toBe(false);
  });
  it("begrenzt die Länge des API-Schlüssels", () => {
    expect(startSchema.safeParse({ ...ok, api_key: "x".repeat(5000) }).success).toBe(false);
    expect(startSchema.safeParse({ ...ok, api_key: "sk-123" }).success).toBe(true);
  });
});

describe("modelsRequestSchema", () => {
  it("prüft Adresse und Schlüssel", () => {
    expect(modelsRequestSchema.safeParse({ base_url: "http://x:8000/v1" }).success).toBe(true);
    expect(modelsRequestSchema.safeParse({ base_url: "gopher://x" }).success).toBe(false);
    expect(modelsRequestSchema.safeParse({}).success).toBe(false);
  });
});

describe("startSchema für Websites", () => {
  const web = { kind: "web", base_url: "https://shop.example/", slo_load: 3 };

  it("verlangt die Bestätigung, dass die Website getestet werden darf", () => {
    expect(startSchema.safeParse(web).success).toBe(false);
    expect(startSchema.safeParse({ ...web, confirm_owner: false }).success).toBe(false);
    const ok = startSchema.safeParse({ ...web, confirm_owner: true, include_assets: false });
    expect(ok.success).toBe(true);
    expect(ok.data).toMatchObject({ kind: "web", confirm_owner: true, include_assets: false, slo_load: 3 });
  });

  it("prüft Art und Grenzen", () => {
    expect(startSchema.safeParse({ ...web, confirm_owner: true, kind: "ftp" }).success).toBe(false);
    expect(startSchema.safeParse({ ...web, confirm_owner: true, slo_load: 0 }).success).toBe(false);
    expect(startSchema.safeParse({ ...web, confirm_owner: true, levels: "1,4,2000" }).success).toBe(false);
  });

  it("braucht die Bestätigung beim KI-Server nicht", () => {
    expect(startSchema.safeParse({ base_url: "http://spark:8000/v1" }).success).toBe(true);
  });
});

describe("startSchema für HTTP-APIs", () => {
  const api = { kind: "api", base_url: "https://api.example/v1/items", confirm_owner: true };

  it("nimmt Methode, Kopfzeilen, Body und erwarteten Status an", () => {
    const r = startSchema.safeParse({
      ...api, method: "POST", expect_status: "201", body: '{"a":1}', slo_load: 0.5,
      headers: [{ name: "Authorization", value: "Bearer abc" }],
    });
    expect(r.success).toBe(true);
    expect(r.data).toMatchObject({ kind: "api", method: "POST", expect_status: "201", headers: [{ name: "Authorization", value: "Bearer abc" }] });
  });

  it("lehnt gefährliche Kopfzeilen und falsche Werte ab", () => {
    expect(startSchema.safeParse({ ...api, method: "TRACE" }).success).toBe(false);
    expect(startSchema.safeParse({ ...api, headers: [{ name: "Host", value: "intern" }] }).success).toBe(false);
    expect(startSchema.safeParse({ ...api, headers: [{ name: "X-A", value: "a\r\nX-B: b" }] }).success).toBe(false);
    expect(startSchema.safeParse({ ...api, headers: [{ name: "X A", value: "a" }] }).success).toBe(false);
    expect(startSchema.safeParse({ ...api, headers: Array.from({ length: 25 }, (_, i) => ({ name: `X-${i}`, value: "a" })) }).success).toBe(false);
    expect(startSchema.safeParse({ ...api, body: "x".repeat(70_000) }).success).toBe(false);
    expect(startSchema.safeParse({ ...api, expect_status: "alles" }).success).toBe(false);
    expect(startSchema.safeParse({ ...api, confirm_owner: false }).success).toBe(false);
  });
});

describe("parseHeaderLines", () => {
  it("liest Kopfzeilen zeilenweise und überspringt Leerzeilen", () => {
    expect(parseHeaderLines("Authorization: Bearer abc\n\nX-Mandant:  42 \n")).toEqual([
      { name: "Authorization", value: "Bearer abc" },
      { name: "X-Mandant", value: "42" },
    ]);
  });
  it("meldet Zeilen ohne Doppelpunkt", () => {
    expect(() => parseHeaderLines("kaputt")).toThrow(/Name: Wert/);
  });
});

describe("startSchema für Abläufe", () => {
  const steps = 'öffne https://chat.example/login\ntippe in "Passwort" {passwort}\nmessen ab hier\nklicke "Senden"';
  const flow = { kind: "flow", base_url: "https://chat.example/login", confirm_owner: true, steps };

  it("nimmt Schritte und Platzhalter-Werte an", () => {
    const r = startSchema.safeParse({ ...flow, secrets: { passwort: "sehr-geheim" }, slo_load: 10, think_time: 60 });
    expect(r.success).toBe(true);
    expect(r.data).toMatchObject({ kind: "flow", steps, secrets: { passwort: "sehr-geheim" } });
  });

  it("verlangt Schritte, Bestätigung und saubere Platzhalter-Namen", () => {
    expect(startSchema.safeParse({ ...flow, steps: undefined }).success).toBe(false);
    expect(startSchema.safeParse({ ...flow, steps: "   " }).success).toBe(false);
    expect(startSchema.safeParse({ ...flow, confirm_owner: false }).success).toBe(false);
    expect(startSchema.safeParse({ ...flow, steps: "x".repeat(21_000) }).success).toBe(false);
    expect(startSchema.safeParse({ ...flow, secrets: { "böse name": "a" } }).success).toBe(false);
    expect(startSchema.safeParse({ ...flow, secrets: { pw: "a".repeat(2000) } }).success).toBe(false);
    expect(startSchema.safeParse({ ...flow, secrets: Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`p${i}`, "a"])) }).success).toBe(false);
  });
});
