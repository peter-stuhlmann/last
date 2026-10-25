import { describe, expect, it } from "vitest";
import { finishedSummary } from "@/test/fixtures";
import { initialLive, parseLogLine, reduceLive } from "./events";
import type { Summary } from "./types";

describe("reduceLive", () => {
  it("sammelt Protokoll, Messpunkte und Zustand", () => {
    let s = reduceLive(initialLive, { type: "reset", run: "results_1" });
    s = reduceLive(s, { type: "log", lines: ["[23:39:12] a", "[23:39:13] b"] });
    s = reduceLive(s, { type: "samples", samples: [{ t: 2, phase: "idle" }] });
    s = reduceLive(s, {
      type: "state",
      state: "running",
      error: null,
      run: "results_1",
      report: false,
      pdf: false,
      summary: finishedSummary(),
    });
    expect(s.connected).toBe(true);
    expect(s.run).toBe("results_1");
    expect(s.state).toBe("running");
    expect(s.logs).toHaveLength(2);
    expect(s.samples).toHaveLength(1);
    expect(s.summary?.config.model).toBe("brain");
  });

  it("setzt bei einem neuen Lauf alles zurück", () => {
    let s = reduceLive(initialLive, { type: "log", lines: ["x"] });
    s = reduceLive(s, { type: "reset", run: "results_2" });
    expect(s.logs).toEqual([]);
    expect(s.samples).toEqual([]);
    expect(s.summary).toBeNull();
  });

  it("begrenzt den Speicher bei langen Läufen", () => {
    let s = initialLive;
    for (let i = 0; i < 30; i++) {
      s = reduceLive(s, { type: "log", lines: Array.from({ length: 100 }, (_, j) => `Zeile ${i}-${j}`) });
      s = reduceLive(s, { type: "samples", samples: Array.from({ length: 400 }, (_, j) => ({ t: i * 400 + j, phase: "soak" })) });
    }
    expect(s.logs.length).toBeLessThanOrEqual(400);
    expect(s.logs[s.logs.length - 1]).toBe("Zeile 29-99");
    expect(s.samples.length).toBeLessThanOrEqual(4000);
    expect(s.samples[s.samples.length - 1].t).toBe(29 * 400 + 399);
  });
});

describe("parseLogLine", () => {
  it("trennt Uhrzeit und Text und erkennt die Art der Zeile", () => {
    expect(parseLogLine("[23:39:12] ━━ 2/6 Immer mehr gleichzeitig ━━")).toEqual({
      time: "23:39:12",
      text: "━━ 2/6 Immer mehr gleichzeitig ━━",
      kind: "heading",
    });
    expect(parseLogLine("[23:41:21] ✓ Bericht fertig.").kind).toBe("good");
    expect(parseLogLine("[23:41:21] ✗ Unerwarteter Fehler").kind).toBe("bad");
    expect(parseLogLine("[23:40:49]     32 gleichzeitig: 30s messen …").kind).toBe("stage");
    expect(parseLogLine("ohne Zeit")).toEqual({ time: "", text: "ohne Zeit", kind: "plain" });
  });
});

describe("frisch gestarteter Lauf", () => {
  it("füllt Felder auf, die das Backend erst nach den ersten Messungen schickt", () => {
    const early = { config: finishedSummary().config, meta: { local_monitor: false } } as unknown as Summary;
    const s = reduceLive(initialLive, {
      type: "state",
      state: "running",
      error: null,
      run: "results_1",
      report: false,
      pdf: false,
      summary: early,
    });
    expect(s.summary?.capacity).toEqual({ think_time: 60, users: null, source: null });
    expect(s.summary?.probes).toBeNull();
    expect(s.summary?.economics).toBeNull();
    expect(s.summary?.verdict.reasons).toEqual([]);
  });
});

describe("Verbindung zum Ereignis-Strom", () => {
  it("merkt sich einen Abbruch, ohne den letzten Stand zu verlieren", () => {
    let s = reduceLive(initialLive, { type: "log", lines: ["a"] });
    s = reduceLive(s, { type: "offline" });
    expect(s.offline).toBe(true);
    expect(s.logs).toEqual(["a"]);
    s = reduceLive(s, { type: "samples", samples: [] });
    expect(s.offline).toBe(false);
  });
});
