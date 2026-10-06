// Verlauf über mehrere Läufe: gleiche Art, gleiche Adresse – wie hat sich die Kapazität entwickelt?
import { terms } from "./derive";
import { hostLabel, nf, runLabel, secs, signedPct } from "./format";
import type { RunInfo, RunKind } from "./types";

export interface TrendGroup {
  key: string;
  kind: RunKind;
  label: string;
  /** Einheit der Kapazität: Besucher, Anfragen/min, Nutzer */
  unit: string;
  /** Bezeichnung der Zeit ohne Andrang: Ladezeit, Antwortzeit, Wartezeit */
  wait: string;
  /** älteste zuerst */
  runs: RunInfo[];
}

const KIND_NAME: Record<RunKind, string> = { llm: "KI-Server", web: "Website", api: "HTTP-API", flow: "Ablauf" };

function pathLabel(baseUrl: string | null): string {
  const host = hostLabel(baseUrl);
  try {
    const u = new URL(baseUrl ?? "");
    const path = u.pathname.replace(/\/+$/, "");
    return path && path !== "/v1" ? `${host}${path}` : host;
  } catch {
    return host;
  }
}

/** Läufe nach Art und Ziel gruppieren – nur Läufe mit Kapazität, älteste zuerst. */
export function trendGroups(runs: RunInfo[]): TrendGroup[] {
  const groups = new Map<string, TrendGroup>();
  for (const r of [...runs].sort((a, b) => a.name.localeCompare(b.name))) {
    if (r.users == null) continue;
    const kind: RunKind = r.kind ?? "llm";
    const key = `${kind}|${r.base_url ?? ""}${kind === "llm" && r.model ? `|${r.model}` : ""}`;
    if (!groups.has(key)) {
      const t = terms({ kind });
      const label = `${KIND_NAME[kind]} · ${pathLabel(r.base_url)}${kind === "llm" && r.model ? ` · ${r.model}` : ""}`;
      groups.set(key, { key, kind, label, unit: t.capacityUnit, wait: t.wait, runs: [] });
    }
    groups.get(key)!.runs.push(r);
  }
  // Gruppen mit dem jüngsten Lauf zuerst
  return [...groups.values()].sort((a, b) => b.runs[b.runs.length - 1].name.localeCompare(a.runs[a.runs.length - 1].name));
}

function dateOf(name: string): string {
  return runLabel(name).split(",")[0];
}

function plural(unit: string, n: number): string {
  // „Besucher“ und „Nutzer“ sind schon Mehrzahl; im Dativ nach „bei rund“ bekommen sie ein n
  if (unit === "Anfragen/min") return unit;
  return n === 1 ? unit : `${unit}n`;
}

/** Ein Satz für Menschen: erster gegen letzter Lauf. */
export function trendText(g: TrendGroup): string {
  const first = g.runs[0];
  const last = g.runs[g.runs.length - 1];
  if (!first || first === last) return "";
  const u0 = first.users ?? 0;
  const u1 = last.users ?? 0;
  const pct = u0 > 0 ? (u1 / u0 - 1) * 100 : null;
  const since = `Seit dem ${dateOf(first.name)}`;
  let cap: string;
  if (pct != null && Math.abs(pct) < 5) {
    cap = `${since} blieb die Kapazität bei rund ${nf(Math.round(u0 / 10) * 10, 0)} ${plural(g.unit, u0)}`;
  } else {
    const dir = u1 >= u0 ? "gestiegen" : "gesunken";
    cap = `${since} ist die Kapazität von ${nf(u0, 0)} auf ${nf(u1, 0)} ${g.unit} ${dir}${pct != null ? ` (${signedPct(pct)})` : ""}`;
  }
  const a0 = first.alone;
  const a1 = last.alone;
  let wait = "";
  if (a0 != null && a1 != null) {
    const rel = a0 > 0 ? a1 / a0 - 1 : 0;
    wait =
      Math.abs(rel) < 0.1
        ? `; die ${g.wait} ohne Andrang blieb bei ${secs(a1)}`
        : `; die ${g.wait} ohne Andrang ${rel < 0 ? "sank" : "stieg"} von ${secs(a0)} auf ${secs(a1)}`;
  }
  return `${cap}${wait}.`;
}

export interface RunFilter {
  text: string;
  kind: RunKind | null;
}

/** Freitext über Titel, Tags (#tag), Adresse, Modell und Datum; Art als Schalter. Angepinnte zuerst. */
export function filterRuns(runs: RunInfo[], f: RunFilter): RunInfo[] {
  const q = f.text.trim().toLowerCase();
  const tagOnly = q.startsWith("#") ? q.slice(1) : null;
  const out = runs.filter((r) => {
    if (f.kind && (r.kind ?? "llm") !== f.kind) return false;
    if (!q) return true;
    if (tagOnly != null) return r.tags.some((t) => t.includes(tagOnly));
    const hay = [r.title ?? "", ...r.tags, r.base_url ?? "", r.model ?? "", runLabel(r.name)].join(" ").toLowerCase();
    return hay.includes(q);
  });
  return out.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.name.localeCompare(a.name));
}
