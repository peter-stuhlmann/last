import { describe, expect, it } from "vitest";
import { config, finishedSummary, stats, step, webSummary } from "@/test/fixtures";
import {
  ampelRows,
  capacityView,
  costView,
  curvePoints,
  terms,
  deriveRamp,
  kpiCards,
  liveFocus,
  liveHeadline,
  meetsSlo,
  phaseOfSample,
  phaseSteps,
  progress,
  stageTimer,
  verdictView,
} from "./derive";
import type { Sample } from "./types";

describe("meetsSlo", () => {
  it("verlangt keine Fehler, kurze Wartezeit und genug Tempo", () => {
    expect(meetsSlo(stats(), config)).toBe(true);
    expect(meetsSlo(stats({ error_rate: 0.01 }), config)).toBe(false);
    expect(meetsSlo(stats({ ttft_p95: 2.5 }), config)).toBe(false);
    expect(meetsSlo(stats({ user_tps_p50: 9 }), config)).toBe(false);
    expect(meetsSlo(stats({ ttft_p95: null }), config)).toBe(false);
  });
});

describe("deriveRamp", () => {
  it("findet Sweet Spot und Höchstleistung", () => {
    const d = deriveRamp(finishedSummary());
    expect(d.rec?.concurrency).toBe(32);
    expect(d.max?.concurrency).toBe(64);
    expect(d.max?.out_tps).toBe(700);
  });
  it("kommt ohne Stufentest zurecht", () => {
    expect(deriveRamp(finishedSummary({ ramp: undefined }))).toEqual({ rec: null, max: null, steps: [] });
  });
});

describe("phaseOfSample", () => {
  it("ordnet Messpunkte den Testschritten zu", () => {
    expect(phaseOfSample("ramp_c32")).toBe("ramp");
    expect(phaseOfSample("rate_120")).toBe("rate");
    expect(phaseOfSample("ctx_8192")).toBe("context");
    expect(phaseOfSample("spike_recovery")).toBe("spike");
    expect(phaseOfSample("baseline")).toBe("baseline");
    expect(phaseOfSample("idle")).toBeNull();
    expect(phaseOfSample("probes")).toBeNull();
  });
});

function running() {
  const s = finishedSummary();
  return {
    ...s,
    meta: { started: "2026-10-04T23:41:00", current_test: "ramp" as const },
    ramp: { steps: s.ramp!.steps.slice(0, 3), break: null, saturated: null },
    rate: undefined,
    context: undefined,
    spike: undefined,
    soak: undefined,
    control: undefined,
    quality: undefined,
  };
}

const samples: Sample[] = [
  { t: 2, phase: "probes" },
  { t: 20, phase: "baseline" },
  { t: 60, phase: "baseline" },
  { t: 72, phase: "ramp_c1" },
  { t: 110, phase: "ramp_c4" },
  { t: 150, phase: "ramp_c16" },
  { t: 190, phase: "ramp_c32", kv: 72, waiting: 3 },
];

describe("phaseSteps", () => {
  it("markiert erledigte, aktive und offene Schritte", () => {
    const steps = phaseSteps(running(), samples, true);
    expect(steps.map((s) => s.key)).toEqual([
      "prechecks", "baseline", "ramp", "rate", "context", "spike", "soak", "control",
    ]);
    expect(steps.map((s) => s.status)).toEqual([
      "done", "done", "active", "pending", "pending", "pending", "pending", "pending",
    ]);
    expect(steps[1].duration).toBe(40);
    expect(steps[2].detail).toBe("Stufe 4 von 5 · 32 gleichzeitig");
  });
  it("lässt abgewählte Tests weg", () => {
    const s = running();
    const steps = phaseSteps({ ...s, config: { ...s.config, tests: "baseline,ramp" } }, samples, true);
    expect(steps.map((x) => x.key)).toEqual(["prechecks", "baseline", "ramp", "control"]);
  });
  it("zeigt nach dem Ende nichts mehr als aktiv", () => {
    const steps = phaseSteps(finishedSummary(), samples, false);
    expect(steps.every((s) => s.status === "done")).toBe(true);
  });
});

describe("liveFocus", () => {
  it("zeigt die aktuelle Stufe des Stufentests", () => {
    expect(liveFocus(running(), samples)).toEqual({
      label: "Stufe 4 / 5",
      value: "32",
      unit: "gleichzeitig",
      fraction: 0.8,
    });
  });
  it("zeigt bei echtem Andrang Fragen pro Minute", () => {
    const f = liveFocus({ ...running(), meta: { current_test: "rate" } }, [{ t: 300, phase: "rate_120" }]);
    expect(f.value).toBe("120");
    expect(f.unit).toBe("Fragen pro Minute");
  });
  it("hat einen ruhigen Startzustand", () => {
    const f = liveFocus({ ...running(), meta: { current_test: null }, ramp: undefined }, []);
    expect(f.value).toBe("–");
  });
});

describe("progress", () => {
  it("schätzt Fortschritt und Restzeit aus der Konfiguration", () => {
    const p = progress(running(), samples);
    expect(p.elapsed).toBe(190);
    expect(p.pct).toBeGreaterThan(10);
    expect(p.pct).toBeLessThan(60);
    expect(p.remaining).toBeGreaterThan(300);
  });
  it("bleibt in den Grenzen 0–99 %", () => {
    const p = progress(running(), [{ t: 99999, phase: "ramp_c32" }]);
    expect(p.pct).toBeLessThanOrEqual(99);
    expect(p.remaining).toBeGreaterThanOrEqual(0);
  });
});

describe("liveHeadline", () => {
  it("lobt, solange die Ziele gehalten werden", () => {
    const h = liveHeadline(running());
    expect(h.tone).toBe("good");
    expect(h.title).toBe("Der Server hält mit.");
    expect(h.text).toContain("16 Personen");
  });
  it("warnt, wenn Ziele verfehlt werden, und meldet Fehler", () => {
    const s = running();
    s.ramp!.steps.push(step(64, { ttft_p95: 3.9 }));
    expect(liveHeadline(s).tone).toBe("warn");
    s.ramp!.steps.push(step(128, { error_rate: 0.2 }));
    expect(liveHeadline(s).tone).toBe("bad");
  });
  it("wartet auf erste Messwerte", () => {
    expect(liveHeadline({ ...running(), ramp: undefined, baseline: undefined }).tone).toBe("none");
  });
});

describe("verdictView", () => {
  it("übersetzt den Status in die Ampel", () => {
    expect(verdictView(finishedSummary()).title).toBe("Grünes Licht.");
    const warn = finishedSummary();
    warn.verdict = { status: "warn", headline: "x", reasons: [] };
    expect(verdictView(warn).title).toBe("Gelbes Licht.");
    warn.verdict = { status: "bad", headline: "x", reasons: [] };
    expect(verdictView(warn).title).toBe("Rotes Licht.");
  });
  it("zeigt ohne Lasttests kein Urteil", () => {
    const s = finishedSummary({ ramp: undefined, rate: undefined });
    s.verdict = { status: "warn", headline: "Für ein Urteil fehlen die Lasttests.", reasons: [] };
    s.capacity = { think_time: 60, users: null, source: null };
    expect(verdictView(s).title).toBe("Noch kein Urteil.");
  });
});

describe("capacityView", () => {
  it("vergleicht Kapazität mit dem Bedarf", () => {
    const c = capacityView(finishedSummary());
    expect(c.users).toBe(140);
    expect(c.target).toBe(80);
    expect(c.reservePct).toBe(75);
    expect(c.targetFraction).toBeCloseTo(0.4, 1);
    expect(c.usersFraction).toBeCloseTo(0.7, 1);
  });
  it("kommt ohne Bedarf aus", () => {
    const s = finishedSummary();
    s.config = { ...s.config, target_users: 0 };
    const c = capacityView(s);
    expect(c.target).toBeNull();
    expect(c.reservePct).toBeNull();
  });
});

describe("kpiCards", () => {
  it("liefert die vier Kennzahlen", () => {
    const k = kpiCards(finishedSummary());
    expect(k.map((x) => `${x.value} ${x.unit}`)).toEqual([
      "0,32 s", "32 gleichzeitig", "700 tok/s", "100 %",
    ]);
    expect(k[2].text).toContain("526 Wörter");
    expect(k[3].text).toContain("48 Kontrollfragen");
  });
  it("zeigt Striche, wenn Tests fehlen", () => {
    const k = kpiCards(finishedSummary({ baseline: undefined, ramp: undefined, probes: null }));
    expect(k.map((x) => x.value)).toEqual(["–", "–", "–", "–"]);
  });
});

describe("ampelRows", () => {
  it("bewertet alle sieben Prüfungen", () => {
    const rows = ampelRows(finishedSummary());
    expect(rows.map((r) => r.status)).toEqual(["good", "good", "good", "warn", "good", "good", "good"]);
    expect(rows[0].value).toBe("0,32 – 1,4 s");
    expect(rows[1].value).toBe("18 – 54 tok/s");
    expect(rows[2].value).toBe("bis 120 Fragen/min");
    expect(rows[3].label).toBe("Lange Texte (32.768 Tokens)");
    expect(rows[3].value).toBe("8,4 s bis zum 1. Wort");
    expect(rows[6].value).toBe("−2 % zum Anfang");
  });
  it("kennzeichnet nicht gelaufene Tests", () => {
    const rows = ampelRows(finishedSummary({ spike: undefined, soak: undefined }));
    expect(rows[4].status).toBe("none");
    expect(rows[4].value).toBe("nicht getestet");
  });
  it("meldet Absturz und Ermüdung", () => {
    const s = finishedSummary();
    s.spike = { ...s.spike!, crashed: true, recovered: false };
    s.soak = { ...s.soak!, degradation: { tps_change_pct: -18, ttft_change_pct: 30 } };
    const rows = ampelRows(s);
    expect(rows[4].status).toBe("bad");
    expect(rows[5].status).toBe("warn");
    expect(rows[5].value).toContain("−18 %");
  });
});

describe("costView", () => {
  it("rechnet Ersparnis beim eigenen Bedarf", () => {
    const c = costView(finishedSummary())!;
    expect(c.own).toBe("0,41 €");
    expect(c.cloud).toBe("1,20 €");
    expect(c.ownFraction).toBeCloseTo(0.34, 2);
    expect(c.needPct).toBe(57);
    // 4000 € × 57 % − 155 € = 2.125 €
    expect(c.savings).toBe("≈ 2.150 €");
    expect(c.breakeven).toBe("34 %");
    expect(c.placeholder).toBe(true);
  });
  it("erkennt eigene Preise", () => {
    const s = finishedSummary();
    s.economics = { ...s.economics!, hw_price: 5200 };
    expect(costView(s)!.placeholder).toBe(false);
  });
  it("gibt null zurück, wenn nichts berechnet wurde", () => {
    expect(costView(finishedSummary({ economics: null }))).toBeNull();
  });
});

describe("stageTimer", () => {
  it("zählt die laufende Stufe herunter", () => {
    const t = stageTimer(running(), [...samples, { t: 200, phase: "ramp_c32" }]);
    // Anlauf 5 s + Messung 30 s = 35 s, davon sind 10 s vorbei
    expect(t).toEqual({ remaining: 25, fraction: 10 / 35 });
  });
  it("gibt außerhalb des Stufentests nichts zurück", () => {
    expect(stageTimer(running(), [{ t: 5, phase: "baseline" }])).toBeNull();
    expect(stageTimer(running(), [])).toBeNull();
  });
});

describe("Website-Läufe", () => {
  const web = () => webSummary();

  it("misst das Ziel an der Ladezeit statt am Lesetempo", () => {
    const cfg = web().config;
    expect(meetsSlo(stats({ user_tps_p50: null, e2e_p95: 2.9 }), cfg)).toBe(true);
    expect(meetsSlo(stats({ user_tps_p50: null, e2e_p95: 3.1 }), cfg)).toBe(false);
    expect(meetsSlo(stats({ user_tps_p50: null, e2e_p95: 1, error_rate: 0.1 }), cfg)).toBe(false);
  });

  it("findet Sweet Spot und Höchstleistung in Seiten pro Sekunde", () => {
    const d = deriveRamp(web());
    expect(d.rec?.concurrency).toBe(32);
    expect(d.max?.concurrency).toBe(64);
    expect(curvePoints(web()).map((p) => [p.c, p.tps, p.ttft, p.ok])).toEqual([
      [1, 1.5, 0.7, true], [16, 20, 1.1, true], [32, 31, 2.4, true], [64, 34, 6.5, false],
    ]);
  });

  it("spricht von Besuchern und Seiten", () => {
    const t = terms(web().config);
    expect(t.people).toBe("Besucher");
    expect(t.throughputUnit).toBe("Seiten/s");
    expect(terms(finishedSummary().config).throughputUnit).toBe("tok/s");
  });

  it("zeigt live Ladezeit, erste Antwort, Seiten pro Sekunde und Fehler", () => {
    const s = web();
    s.ramp!.steps = s.ramp!.steps.slice(0, 3);
    const h = liveHeadline(s);
    expect(h.tone).toBe("good");
    expect(h.title).toBe("Die Website hält mit.");
    expect(h.text).toContain("32 Besucher");
    expect(h.kpis.map((k) => `${k.label}: ${k.value} ${k.unit}`)).toEqual([
      "Seite geladen nach: 2,4 s", "Erste Antwort: 0,90 s", "Seiten pro Sekunde: 31 Seiten/s", "Fehler: 0,0 %",
    ]);
    expect(liveHeadline(web()).tone).toBe("warn");
  });

  it("liefert passende Kennzahlen und Ampelzeilen", () => {
    expect(kpiCards(web()).map((k) => `${k.label}: ${k.value} ${k.unit}`)).toEqual([
      "Einer allein: 0,60 s", "Sweet Spot: 32 gleichzeitig", "Höchstleistung: 34 Seiten/s", "Erste Antwort: 0,08 s",
    ]);
    const rows = ampelRows(web());
    expect(rows.map((r) => r.label)).toEqual([
      "Ladezeit bei normaler Last", "Erste Antwort des Servers", "Echter Andrang",
      "Großer Ansturm", "Ausdauer über 3 Minuten", "Kontrollmessung am Ende",
    ]);
    expect(rows[0].value).toBe("0,60 – 2,4 s");
    expect(rows[2].value).toBe("bis 1.500 Aufrufe/min");
    expect(rows.every((r) => r.status === "good")).toBe(true);
  });

  it("hat keinen Kostenvergleich und keine Schritte für lange Texte", () => {
    expect(costView(web())).toBeNull();
    const steps = phaseSteps(web(), [], false);
    expect(steps.map((s) => s.key)).toEqual(["prechecks", "baseline", "ramp", "rate", "spike", "soak", "control"]);
    expect(steps[1].detail).toBe("Bestwert: Seite nach 0,60 s geladen");
    expect(steps[0].detail).toBe("Erreichbar, 12 Dateien gehören zur Seite");
  });
});

describe("Verlässlichkeit der Messung", () => {
  const item = (status: "good" | "warn" | "bad", value: string) => ({
    status, title: "Kam der Messrechner hinterher?", value, text: "",
  });

  it("warnt in der Ampel, wenn der Messrechner überlastet war", () => {
    const s = webSummary({ quality: { overall: "niedrig", items: [item("good", "ja"), item("bad", "nein (400 ms bei 64 gleichzeitig)")] } });
    const row = ampelRows(s).at(-1)!;
    expect(row.label).toBe("Verlässlichkeit der Messung");
    expect(row.status).toBe("bad");
    expect(row.value).toBe("niedrig – Kam der Messrechner hinterher? nein (400 ms bei 64 gleichzeitig)");
  });

  it("bestätigt eine saubere Messung – auch beim KI-Server", () => {
    const row = ampelRows(finishedSummary({ quality: { overall: "hoch", items: [item("good", "ja")] } })).at(-1)!;
    expect(row).toEqual({ label: "Verlässlichkeit der Messung", value: "hoch – die Messung war sauber", status: "good" });
    const mid = ampelRows(webSummary({ quality: { overall: "mittel", items: [item("warn", "knapp (80 ms)")] } })).at(-1)!;
    expect(mid.status).toBe("warn");
  });

  it("lässt die Zeile weg, solange nichts geprüft wurde", () => {
    expect(ampelRows(webSummary()).map((r) => r.label)).not.toContain("Verlässlichkeit der Messung");
  });
});
