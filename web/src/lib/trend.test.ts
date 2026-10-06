import { describe, expect, it } from "vitest";
import type { RunInfo } from "./types";
import { filterRuns, trendGroups, trendText } from "./trend";

function run(name: string, over: Partial<RunInfo> = {}): RunInfo {
  return {
    name, kind: "web", model: null, base_url: "https://shop.example/", started: null, tests: ["ramp"], report: true, pdf: true,
    title: null, tags: [], note: "", pinned: false, users: 400, target_users: 500, status: "warn", alone: 0.8, ...over,
  };
}

const runs: RunInfo[] = [
  run("results_20260901_100000", { users: 410, alone: 0.9, status: "bad" }),
  run("results_20260915_100000", { users: 520, alone: 0.7, title: "Cache an", tags: ["shop", "cache"] }),
  run("results_20261001_100000", { users: 770, alone: 0.6, status: "good", pinned: true }),
  run("results_20261002_100000", { kind: "api", base_url: "https://api.example/v1/items", users: 1500, alone: 0.05, status: "good" }),
  run("results_20261003_100000", { kind: "llm", base_url: "http://spark:8000/v1", model: "qwen", users: 24, alone: 0.3 }),
  run("results_20261004_100000", { users: null, status: null }), // abgebrochen – keine Kapazität
];

describe("trendGroups", () => {
  it("gruppiert nach Art und Adresse (zuletzt getestete Gruppe zuerst), Läufe älteste zuerst, nur mit Kapazität", () => {
    const groups = trendGroups(runs);
    expect(groups.map((g) => g.label)).toEqual(["KI-Server · spark:8000 · qwen", "HTTP-API · api.example/v1/items", "Website · shop.example"]);
    expect(groups[2].runs.map((r) => r.name)).toEqual(["results_20260901_100000", "results_20260915_100000", "results_20261001_100000"]);
    expect(groups[2].unit).toBe("Besucher");
    expect(groups[1].unit).toBe("Anfragen/min");
  });

  it("zeigt nur Gruppen mit mindestens zwei Läufen als Verlauf an", () => {
    expect(trendGroups(runs).filter((g) => g.runs.length >= 2).map((g) => g.key)).toEqual(["web|https://shop.example/"]);
  });
});

describe("trendText", () => {
  it("vergleicht den ersten mit dem letzten Lauf in einem Satz", () => {
    const g = trendGroups(runs).find((x) => x.kind === "web")!;
    expect(trendText(g)).toBe(
      "Seit dem 01.09.2026 ist die Kapazität von 410 auf 770 Besucher gestiegen (+88 %); die Ladezeit ohne Andrang sank von 0,90 s auf 0,60 s.",
    );
  });

  it("benennt auch Verschlechterung und Stillstand", () => {
    const worse = trendGroups([run("results_20260901_100000", { users: 800, alone: 0.5 }), run("results_20260902_100000", { users: 600, alone: 0.5 })])[0];
    expect(trendText(worse)).toContain("von 800 auf 600 Besucher gesunken (−25 %)");
    expect(trendText(worse)).toContain("blieb bei 0,50 s");
    const same = trendGroups([run("results_20260901_100000", { users: 600 }), run("results_20260902_100000", { users: 610 })])[0];
    expect(trendText(same)).toContain("blieb die Kapazität bei rund 600 Besuchern");
  });
});

describe("filterRuns", () => {
  it("sucht in Titel, Tags, Adresse und Modell – und nach Art", () => {
    expect(filterRuns(runs, { text: "cache", kind: null }).map((r) => r.name)).toEqual(["results_20260915_100000"]);
    expect(filterRuns(runs, { text: "shop.example", kind: null })).toHaveLength(4);
    expect(filterRuns(runs, { text: "", kind: "api" })).toHaveLength(1);
    expect(filterRuns(runs, { text: "qwen", kind: "llm" })).toHaveLength(1);
    expect(filterRuns(runs, { text: "#cache", kind: null })).toHaveLength(1);
  });

  it("setzt angepinnte Läufe nach oben", () => {
    expect(filterRuns(runs, { text: "", kind: null })[0].name).toBe("results_20261001_100000");
  });
});
