// Macht aus den Rohdaten des Backends das, was die Oberfläche in einfachen Worten zeigt.
import { approxUsers, eur, nf, perMinute, secs, signedPct, splitSecs } from "./format";
import type { RampStep, RunConfig, Sample, Stats, Summary, TestKey, Tone } from "./types";

export type Status = Tone | "none";
export type StepKey = "prechecks" | TestKey;

const TEST_ORDER: TestKey[] = ["baseline", "ramp", "rate", "context", "spike", "soak", "control"];

type Cfg = Pick<RunConfig, "kind" | "slo_ttft" | "slo_user_tps" | "slo_load">;

const isWeb = (cfg: Pick<RunConfig, "kind">) => cfg.kind === "web";
const isApi = (cfg: Pick<RunConfig, "kind">) => cfg.kind === "api";
const isFlow = (cfg: Pick<RunConfig, "kind">) => cfg.kind === "flow";
/** Website, API und Ablauf messen Lade- bzw. Antwortzeiten statt Tokens. */
const isTimed = (cfg: Pick<RunConfig, "kind">) => isWeb(cfg) || isApi(cfg) || isFlow(cfg);

/** Bis zu einem Fehler auf tausend gilt als sauber – wie im Backend (llm_stresstest.ERR_OK). */
export const ERR_OK = 0.001;

export interface Terms {
  subject: string;
  /** „Besucher“, „Anfragen“, „Nutzer“ – Mehrzahl */
  people: string;
  /** einer davon: „Besucher“, „Anfrage“, „Nutzer“, „Person“ */
  one: string;
  peopleLong: string;
  capacityUnit: string;
  throughput: string;
  throughputUnit: string;
  wait: string;
  perMinute: string;
  /** was eine Fehlerzahl zählt: „Aufrufen“, „Anfragen“, „Durchläufen“ */
  errorsOf: string;
  goal: (s: number) => string;
  /** Live-Überschrift: einer allein / n gleichzeitig */
  alone: string;
  together: (n: number) => string;
  /** Live-Kennzahl: wonach die Zielzeit gemessen wird */
  waitLabel: string;
  /** Ergebnis-Karte „Einer allein“ */
  aloneText: string;
  /** Ergebnis-Karte „Erste Antwort“ */
  firstText: string;
  /** Live-Texte je Zustand */
  failText: string;
  slowText: string;
  goodAlone: string;
  goodAll: string;
  /** Zeitleiste: was der Vorab-Check klärt */
  preQuestion: string;
}

/** Begriffe, die sich zwischen KI-Server, Website, HTTP-API und Ablauf unterscheiden. */
export function terms(cfg: Pick<RunConfig, "kind">): Terms {
  if (isApi(cfg)) {
    return {
      subject: "Die API",
      people: "Anfragen",
      one: "Anfrage",
      peopleLong: "Anfragen pro Minute, die flüssig durchgehen",
      capacityUnit: "Anfragen/min",
      throughput: "Anfragen pro Sekunde",
      throughputUnit: "Anfr./s",
      wait: "Antwortzeit",
      perMinute: "Anfragen",
      errorsOf: "Anfragen",
      goal: (s: number) => `Ziel: Antwort nach höchstens ${secs(s)}`,
      alone: "Eine Anfrage läuft allein",
      together: (n) => `${n} Anfragen laufen gleichzeitig`,
      waitLabel: "Antwort nach",
      aloneText: "bis die Antwort komplett da ist, wenn sonst niemand fragt",
      firstText: "so schnell reagiert der Server, bevor die Antwort kommt",
      failText: "und manche enden mit einem Fehler.",
      slowText: "die Antworten kommen, aber langsamer als gewünscht.",
      goodAlone: "und wird schnell genug beantwortet.",
      goodAll: "und alle werden schnell genug beantwortet.",
      preQuestion: "Erreichbar? Antwortet sie wie erwartet?",
    };
  }
  if (isFlow(cfg)) {
    return {
      subject: "Die Anwendung",
      people: "Nutzer",
      one: "Nutzer",
      peopleLong: "Nutzer gleichzeitig in der Anwendung",
      capacityUnit: "Nutzer",
      throughput: "Durchläufe pro Sekunde",
      throughputUnit: "Durchl./s",
      wait: "Antwortzeit",
      perMinute: "Durchläufe",
      errorsOf: "Durchläufen",
      goal: (s: number) => `Ziel: Antwort nach höchstens ${secs(s)}`,
      alone: "Ein Nutzer macht den Ablauf allein",
      together: (n) => `${n} Nutzer machen den Ablauf gleichzeitig`,
      waitLabel: "Antwort nach",
      aloneText: "bis die Antwort komplett da ist, wenn sonst niemand da ist",
      firstText: "so schnell kommt das erste Lebenszeichen der Antwort",
      failText: "und manche bekommen einen Fehler.",
      slowText: "die Antworten kommen, aber langsamer als gewünscht.",
      goodAlone: "und bekommt die Antwort schnell genug.",
      goodAll: "und alle bekommen ihre Antwort schnell genug.",
      preQuestion: "Schritte im Browser aufzeichnen",
    };
  }
  return isWeb(cfg)
    ? {
        subject: "Die Website",
        people: "Besucher",
        one: "Besucher",
        peopleLong: "Besucher gleichzeitig auf der Website",
        capacityUnit: "Besucher",
        throughput: "Seiten pro Sekunde",
        throughputUnit: "Seiten/s",
        wait: "Ladezeit",
        perMinute: "Aufrufe",
        errorsOf: "Aufrufen",
        goal: (s: number) => `Ziel: Seite nach höchstens ${secs(s)} da`,
        alone: "Ein Besucher lädt die Seite allein",
        together: (n) => `${n} Besucher laden die Seite gleichzeitig`,
        waitLabel: "Seite geladen nach",
        aloneText: "bis die Seite komplett geladen ist, wenn sonst niemand da ist",
        firstText: "so schnell reagiert der Server, bevor die Seite lädt",
        failText: "und manche bekommen eine Fehlerseite.",
        slowText: "sie kommt an, aber langsamer als gewünscht.",
        goodAlone: "und hat sie schnell genug vor sich.",
        goodAll: "und alle haben sie schnell genug vor sich.",
        preQuestion: "Erreichbar? Welche Dateien gehören dazu?",
      }
    : {
        subject: "Der Server",
        people: "Nutzer",
        one: "Person",
        peopleLong: "aktive Nutzer im Team",
        capacityUnit: "Nutzer",
        throughput: "Gesamtleistung",
        throughputUnit: "tok/s",
        wait: "Wartezeit",
        perMinute: "Fragen",
        errorsOf: "Fragen",
        goal: (s: number) => `Ziel: höchstens ${secs(s)} warten`,
        alone: "Eine Person fragt allein",
        together: (n) => `${n} Personen fragen gleichzeitig`,
        waitLabel: "Warten aufs 1. Wort",
        aloneText: "bis zum ersten Wort, wenn sonst niemand fragt",
        firstText: "",
        failText: "und manche bekommen keine Antwort.",
        slowText: "die Antworten kommen, aber langsamer als gewünscht.",
        goodAlone: "und bekommt die Antwort schnell genug.",
        goodAll: "und alle bekommen ihre Antwort schnell genug.",
        preQuestion: "Erreichbar? Frei? Zählt richtig?",
      };
}

/** Das Zeit-Ziel des Laufs: Ladezeit der Seite bzw. Warten aufs erste Wort. */
export function sloSeconds(cfg: Cfg): number {
  return isTimed(cfg) ? (cfg.slo_load ?? (isApi(cfg) ? 0.5 : isFlow(cfg) ? 10 : 3)) : cfg.slo_ttft;
}

/** Die Zeit, an der das Ziel gemessen wird (95 % sind schneller). */
function waitP95(s: Stats, cfg: Cfg): number | null {
  return (isTimed(cfg) ? s.e2e_p95 : s.ttft_p95) ?? null;
}

/** Gesamtleistung: Seiten pro Sekunde bzw. Tokens pro Sekunde. */
function throughput(s: Stats, cfg: Cfg): number | null {
  return (isTimed(cfg) ? s.req_s : s.out_tps) ?? null;
}

export function meetsSlo(s: Stats, cfg: Cfg): boolean {
  const wait = waitP95(s, cfg);
  if (s.error_rate > ERR_OK || wait == null || wait > sloSeconds(cfg)) return false;
  return isTimed(cfg) || (s.user_tps_p50 != null && s.user_tps_p50 >= cfg.slo_user_tps);
}

export function deriveRamp(summary: Summary): { rec: RampStep | null; max: RampStep | null; steps: RampStep[] } {
  const cfg = summary.config;
  const steps = [...(summary.ramp?.steps ?? [])].sort((a, b) => a.concurrency - b.concurrency);
  let rec: RampStep | null = null;
  let max: RampStep | null = null;
  for (const s of steps) {
    if (meetsSlo(s, cfg)) rec = s;
    const t = throughput(s, cfg);
    if (t != null && (max == null || t > (throughput(max, cfg) ?? 0))) max = s;
  }
  return { rec, max, steps };
}

function numberList(value: string | undefined): number[] {
  return (value ?? "")
    .split(",")
    .map(Number)
    .filter((n) => Number.isFinite(n) && n > 0);
}

function selectedTests(summary: Summary): TestKey[] {
  const chosen = (summary.config.tests ?? "").split(",");
  const skipped = summary.skipped ?? [];
  return TEST_ORDER.filter((k) => (k === "control" ? chosen.includes("baseline") : chosen.includes(k) && !skipped.includes(k)));
}

export function phaseOfSample(phase: string): TestKey | null {
  if (phase === "baseline" || phase === "soak" || phase === "control") return phase;
  if (phase.startsWith("ramp_")) return "ramp";
  if (phase.startsWith("rate_")) return "rate";
  if (phase.startsWith("ctx_")) return "context";
  if (phase.startsWith("spike")) return "spike";
  return null;
}

function lastSample(samples: Sample[]): Sample | undefined {
  return samples[samples.length - 1];
}

/** Erster und letzter Messzeitpunkt je Testschritt. */
function phaseTimes(samples: Sample[]): Partial<Record<TestKey, { start: number; end: number }>> {
  const out: Partial<Record<TestKey, { start: number; end: number }>> = {};
  for (const s of samples) {
    const key = phaseOfSample(s.phase);
    if (!key) continue;
    const cur = out[key];
    if (cur) cur.end = s.t;
    else out[key] = { start: s.t, end: s.t };
  }
  return out;
}

function currentConcurrency(samples: Sample[]): number | null {
  const m = /^ramp_c(\d+)$/.exec(lastSample(samples)?.phase ?? "");
  return m ? Number(m[1]) : null;
}

export interface PhaseStep {
  key: StepKey;
  title: string;
  detail: string;
  status: "done" | "active" | "pending";
  duration?: number;
  /** Fortschritt innerhalb des aktiven Schritts, 0–1 */
  fraction?: number;
}

function rampDetail(summary: Summary, samples: Sample[]): { detail: string; fraction: number } | null {
  const c = currentConcurrency(samples);
  if (c == null) return null;
  const levels = numberList(summary.config.levels);
  const idx = levels.indexOf(c);
  if (idx < 0) return { detail: `Feinsuche · ${c} gleichzeitig`, fraction: 0.95 };
  return { detail: `Stufe ${idx + 1} von ${levels.length} · ${c} gleichzeitig`, fraction: (idx + 1) / levels.length };
}

/** Die Zeitleiste links: was ist erledigt, was läuft, was kommt noch. */
/**
 * Kontrollmessung in Worten – wie report_web.control_note: Unterschiede unter 5 % (bei Websites auch unter
 * 0,05 s) sind Messrauschen, und schneller als am Anfang ist nie ein Problem.
 */
function controlView(summary: Summary): { text: string; status: Status } | null {
  const c = summary.control;
  if (!c) return null;
  const web = isTimed(summary.config);
  // Website: Ladezeit (+ heißt langsamer) · KI-Server: Tempo (− heißt langsamer)
  const slower = web ? c.ttft_diff_pct : c.tps_diff_pct != null ? -c.tps_diff_pct : null;
  if (slower == null) return null;
  const a = summary.baseline?.e2e_p50;
  const b = c.s.e2e_p50;
  if (Math.abs(slower) < 5 || (web && a != null && b != null && Math.abs(b - a) < 0.05)) {
    return { text: "so schnell wie am Anfang", status: "good" };
  }
  if (slower < 0) return { text: "schneller als am Anfang", status: "good" };
  return { text: `${nf(slower, 0)} % langsamer als am Anfang`, status: slower > (web ? 25 : 10) ? "warn" : "good" };
}

/** „2 von 35.114 Aufrufen“ – lesbarer als eine auf 0,0 % gerundete Fehlerquote. */
function errorCount(s: Stats, cfg: Cfg): string {
  return `${nf(s.errors, 0)} von ${nf(s.n, 0)} ${terms(cfg).errorsOf}`;
}

export function phaseSteps(summary: Summary, samples: Sample[], running: boolean): PhaseStep[] {
  const cfg = summary.config;
  const web = isTimed(cfg);
  const api = isApi(cfg);
  const t = terms(cfg);
  const active = running ? (summary.meta.current_test ?? null) : null;
  const times = phaseTimes(samples);
  const { rec } = deriveRamp(summary);
  const b = summary.baseline;
  const maxCtx = Math.max(0, ...numberList(cfg.context_lengths));
  const soakMinutes = nf(cfg.soak_minutes, cfg.soak_minutes < 1 ? 1 : 0);
  const control = controlView(summary);

  const texts: Record<TestKey, { title: string; pending: string; done: string }> = {
    baseline: {
      title: "Einer allein",
      pending: "Wie schnell ohne Andrang?",
      done: !b
        ? ""
        : api || isFlow(cfg)
          ? `Bestwert: Antwort nach ${secs(b.e2e_p50)}`
          : web
            ? `Bestwert: Seite nach ${secs(b.e2e_p50)} geladen`
            : `Bestwert: ${secs(b.ttft_p50)} · ${nf(b.user_tps_p50, 0)} tok/s`,
    },
    ramp: {
      title: "Immer mehr gleichzeitig",
      pending: `Bis ${Math.max(0, ...numberList(cfg.levels))} ${web ? t.people : "Personen"} gleichzeitig`,
      done: rec ? `Ziele gehalten bis ${rec.concurrency} gleichzeitig` : "Ziele nicht erreicht",
    },
    rate: {
      title: "Echter Andrang",
      pending: `${web ? t.people : "Fragen"} kommen zufällig, wie im Alltag`,
      done: summary.capacity.rate_ok
        ? `Bis ${perMinute(summary.capacity.rate_ok)} ${t.perMinute} pro Minute`
        : "Schlange wächst schon bei wenig Andrang",
    },
    context: {
      title: "Lange Texte",
      pending: `Bis ${nf(maxCtx, 0)} Tokens ≈ ${nf(maxCtx / 400, 0)} Seiten`,
      done: summary.context?.max_ok ? `Schafft ${nf(summary.context.max_ok, 0)} Tokens` : "Lange Texte scheitern",
    },
    spike: {
      title: "Großer Ansturm",
      pending: `${cfg.spike_size} ${web ? t.people : "Fragen"} auf einmal + Erholung`,
      done: summary.spike?.crashed
        ? web
          ? `${t.subject.split(" ")[1]} nicht mehr erreichbar`
          : "Server abgestürzt"
        : summary.spike?.recovered === false
          ? "Erholt sich nicht"
          : "Erholt sich",
    },
    soak: {
      title: "Ausdauer",
      pending: `${soakMinutes} Minuten gleichmäßige Last`,
      done: "Durchgehalten",
    },
    control: {
      title: "Kontrolle",
      pending: "Noch so schnell wie am Anfang?",
      done: control ? control.text.charAt(0).toUpperCase() + control.text.slice(1) : "",
    },
  };

  const anyData = TEST_ORDER.some((k) => summary[k]) || active != null;
  const pre = summary.prechecks;
  const preDetail =
    isFlow(cfg) && pre?.steps
      ? `Aufgezeichnet: ${pre.steps.length} Schritte, ${pre.requests?.length ?? 0} Anfragen${(pre.accounts ?? 1) > 1 ? `, ${pre.accounts} Konten` : ""}`
      : api && pre?.status != null
        ? `Erreichbar, Status ${pre.status} nach ${nf(pre.rtt_ms, 0)} ms`
        : isWeb(cfg) && pre?.assets != null
          ? `Erreichbar, ${pre.assets} Dateien gehören zur Seite`
          : pre?.rtt_ms != null
            ? `Erreichbar, ${nf(pre.rtt_ms, 0)} ms Netzweg`
            : t.preQuestion;
  const steps: PhaseStep[] = [
    {
      key: "prechecks",
      title: "Vorab-Check",
      detail: preDetail,
      status: pre || anyData ? "done" : running ? "active" : "pending",
    },
  ];

  for (const key of selectedTests(summary)) {
    const text = texts[key];
    const time = times[key];
    const duration = time ? Math.round(time.end - time.start) : undefined;
    if (key === active) {
      const ramp = key === "ramp" ? rampDetail(summary, samples) : null;
      steps.push({
        key,
        title: text.title,
        detail: ramp?.detail ?? text.pending,
        status: "active",
        duration,
        fraction: ramp?.fraction,
      });
    } else if (summary[key]) {
      steps.push({ key, title: text.title, detail: text.done, status: "done", duration });
    } else {
      steps.push({ key, title: text.title, detail: text.pending, status: "pending" });
    }
  }
  return steps;
}

/** Grobe Dauer je Schritt in Sekunden – das Backend liefert keine Restzeit. */
function estimates(summary: Summary): Record<StepKey, number> {
  const c = summary.config;
  const web = isTimed(c);
  return {
    prechecks: isFlow(c) ? 60 : 20,
    baseline: c.baseline_requests * (isFlow(c) ? 6 : web ? 2 : 8),
    ramp: numberList(c.levels).length * (c.warmup_seconds + c.level_seconds + c.cooldown),
    rate: 4 * (c.rate_seconds + c.cooldown),
    context: numberList(c.context_lengths).length * c.context_requests * 10,
    spike: web ? 20 : 60,
    soak: c.soak_minutes * 60,
    control: web ? 10 : 30,
  };
}

export function progress(summary: Summary, samples: Sample[]): { elapsed: number; remaining: number; pct: number } {
  const elapsed = lastSample(samples)?.t ?? 0;
  const est = estimates(summary);
  const times = phaseTimes(samples);
  let remaining = 0;
  for (const s of phaseSteps(summary, samples, true)) {
    if (s.status === "pending") remaining += est[s.key];
    if (s.status === "active") {
      const start = s.key === "prechecks" ? 0 : (times[s.key]?.start ?? elapsed);
      remaining += Math.max(0, est[s.key] - (elapsed - start));
    }
  }
  const total = elapsed + remaining;
  const pct = total > 0 ? Math.min(99, Math.max(0, Math.round((elapsed / total) * 100))) : 0;
  return { elapsed, remaining, pct };
}

export interface Focus {
  label: string;
  value: string;
  unit: string;
  fraction: number;
}

/** Der große Ring: woran wird gerade gemessen? Nach dem Ende („ended“) sagt er, wie es ausgegangen ist. */
export function liveFocus(summary: Summary, samples: Sample[], ended?: "done" | "stopped" | "error"): Focus {
  if (ended === "done") return { label: "Fertig", value: "✓", unit: "erledigt", fraction: 1 };
  if (ended) return { label: ended === "stopped" ? "Abgebrochen" : "Fehler", value: "–", unit: "Test beendet", fraction: 0 };
  const phase = lastSample(samples)?.phase ?? "";
  const test = summary.meta.current_test ?? phaseOfSample(phase);
  const cfg = summary.config;
  const one = terms(cfg).one;
  switch (test) {
    case "baseline":
      return { label: "Einer allein", value: "1", unit: one, fraction: 0.1 };
    case "ramp": {
      const c = currentConcurrency(samples);
      const levels = numberList(cfg.levels);
      if (c == null) return { label: "Stufentest", value: "–", unit: "gleichzeitig", fraction: 0 };
      const idx = levels.indexOf(c);
      return idx < 0
        ? { label: "Feinsuche", value: String(c), unit: "gleichzeitig", fraction: 0.95 }
        : {
            label: `Stufe ${idx + 1} / ${levels.length}`,
            value: String(c),
            unit: "gleichzeitig",
            fraction: (idx + 1) / levels.length,
          };
    }
    case "rate": {
      const raw = Number(/^rate_(.+)$/.exec(phase)?.[1]);
      const n = summary.rate?.stages.length ?? 0;
      return {
        label: "Echter Andrang",
        value: Number.isFinite(raw) ? nf(raw, raw >= 10 ? 0 : 1) : "–",
        unit: `${terms(cfg).perMinute} pro Minute`,
        fraction: Math.min(1, (n + 1) / 5),
      };
    }
    case "context": {
      const tokens = Number(/^ctx_(\d+)$/.exec(phase)?.[1]);
      const lengths = numberList(cfg.context_lengths);
      const idx = lengths.indexOf(tokens);
      return {
        label: "Lange Texte",
        value: Number.isFinite(tokens) ? `${nf(tokens / 1000, 0)}k` : "–",
        unit: "Tokens Text",
        fraction: idx < 0 ? 0.5 : (idx + 1) / lengths.length,
      };
    }
    case "spike":
      return { label: "Großer Ansturm", value: String(cfg.spike_size), unit: "auf einmal", fraction: 1 };
    case "soak":
      return {
        label: "Ausdauer",
        value: nf(cfg.soak_minutes, cfg.soak_minutes < 1 ? 1 : 0),
        unit: "Minuten Dauerlast",
        fraction: 0.6,
      };
    case "control":
      return { label: "Kontrolle", value: "1", unit: one, fraction: 0.1 };
    default:
      return { label: "Vorab-Check", value: "–", unit: "wird geprüft", fraction: 0 };
  }
}

export interface LiveKpi {
  label: string;
  value: string;
  unit: string;
  note: string;
  tone: Status;
}

export interface Headline {
  tone: Status;
  title: string;
  text: string;
  kpis: LiveKpi[];
}

/** Überschrift und vier Kennzahlen aus der zuletzt fertig gemessenen Stufe. */
export function liveHeadline(summary: Summary): Headline {
  const cfg = summary.config;
  const web = isTimed(cfg);
  const t = terms(cfg);
  const steps = summary.ramp?.steps ?? [];
  const last: Stats | undefined = steps[steps.length - 1] ?? summary.baseline;
  if (!last) {
    return { tone: "none", title: "Messung läuft …", text: "Die ersten Werte erscheinen gleich.", kpis: [] };
  }
  const n = steps.length ? steps[steps.length - 1].concurrency : 1;
  const prev = steps.length > 1 ? steps[steps.length - 2] : null;
  const alone = n === 1;
  const who = alone ? t.alone : t.together(n);
  const slo = sloSeconds(cfg);
  const waitValue = waitP95(last, cfg);
  const waitOk = waitValue != null && waitValue <= slo;
  const now = throughput(last, cfg);
  const before = prev ? throughput(prev, cfg) : null;
  const gain = before && now != null ? (now / before - 1) * 100 : null;
  const wait = splitSecs(waitValue);
  const speedOk = last.user_tps_p50 != null && last.user_tps_p50 >= cfg.slo_user_tps;
  const firstByte = splitSecs(last.ttft_p95);

  const kpis: LiveKpi[] = [
    {
      label: t.waitLabel,
      value: wait.value,
      unit: wait.unit,
      note: `${waitOk ? "✓" : "✗"} Ziel ≤ ${nf(slo, 1)} s`,
      tone: waitOk ? "good" : "warn",
    },
    web
      ? {
          label: "Erste Antwort",
          value: firstByte.value,
          unit: firstByte.unit,
          note: "so schnell reagiert der Server",
          tone: "none",
        }
      : {
          label: "Lesetempo",
          value: nf(last.user_tps_p50, 1),
          unit: "tok/s",
          note: speedOk ? "✓ schnell genug zum Mitlesen" : `✗ Ziel ≥ ${nf(cfg.slo_user_tps, 0)} tok/s`,
          tone: speedOk ? "good" : "warn",
        },
    {
      label: t.throughput,
      value: nf(now, web && now != null && now < 10 ? 1 : 0),
      unit: t.throughputUnit,
      note: gain == null ? "alle zusammen" : `${gain >= 0 ? "↗" : "↘"} ${signedPct(gain)} zur Stufe davor`,
      tone: "none",
    },
    {
      label: "Fehler",
      value: nf(last.error_rate * 100, 1),
      unit: "%",
      note: last.error_rate === 0 ? "✓ keine einzige" : `✗ ${last.errors} von ${last.n} ${t.errorsOf}`,
      tone: last.error_rate === 0 ? "good" : "bad",
    },
  ];

  if (last.error_rate > 0) {
    return {
      tone: "bad",
      title: `${t.subject} kommt nicht mehr mit.`,
      text: `${who} – ${t.failText}`,
      kpis,
    };
  }
  if (!meetsSlo(last, cfg)) {
    return {
      tone: "warn",
      title: "Es wird eng.",
      text: `${who} – ${t.slowText}`,
      kpis,
    };
  }
  const goodText = alone ? `${who} ${t.goodAlone}` : `${who} – ${t.goodAll}`;
  return { tone: "good", title: `${t.subject} hält mit.`, text: goodText, kpis };
}

export function verdictView(summary: Summary): {
  status: Status;
  title: string;
  text: string;
  reasons: [Tone | "info", string][];
} {
  const v = summary.verdict;
  const hasLoad = Boolean(summary.ramp || summary.rate);
  if (!hasLoad) {
    return { status: "none", title: "Noch kein Urteil.", text: v.headline, reasons: v.reasons };
  }
  const title = { good: "Grünes Licht.", warn: "Gelbes Licht.", bad: "Rotes Licht." }[v.status];
  return { status: v.status, title, text: v.headline, reasons: v.reasons };
}

export interface CapacityView {
  users: number | null;
  target: number | null;
  reservePct: number | null;
  /** Position auf dem Balken, 0–1 */
  usersFraction: number;
  targetFraction: number;
  /** Woraus die Zahl hochgerechnet ist – damit „4.900“ neben „64 gleichzeitig“ nicht wie ein Widerspruch aussieht */
  basis: string | null;
}

function capacityBasis(summary: Summary): string | null {
  const cfg = summary.config;
  const cap = summary.capacity;
  if (isApi(cfg)) return "So viele Anfragen gingen im Test flüssig durch – zufällig verteilt, wie im Alltag.";
  const t = terms(cfg);
  const measured =
    cap.source === "rate"
      ? `bis zu ${perMinute(cap.rate_ok)} ${t.perMinute} pro Minute`
      : cap.source === "ramp"
        ? `${cap.rec_concurrency} ${t.perMinute} im selben Augenblick`
        : null;
  if (!measured) return null;
  const think = nf(cap.think_time, 0);
  const habit = isFlow(cfg)
    ? `jeder Nutzer nach einem Durchlauf etwa ${think} s Pause macht`
    : isWeb(cfg)
      ? `jeder Besucher etwa alle ${think} s eine Seite aufruft`
      : `jede Person etwa alle ${think} s eine Frage stellt`;
  return `Hochgerechnet: Im Test liefen ${measured} flüssig. Angenommen ist, dass ${habit} – es sind also nie alle im selben Augenblick dran.`;
}

export function capacityView(summary: Summary): CapacityView {
  const users = approxUsers(summary.capacity.users);
  const target = summary.config.target_users > 0 ? summary.config.target_users : null;
  const scale = Math.max(users ?? 0, target ?? 0) / 0.7 || 1;
  return {
    basis: users != null ? capacityBasis(summary) : null,
    users,
    target,
    reservePct: users != null && target != null ? Math.round((users / target - 1) * 100) : null,
    usersFraction: Math.min(1, (users ?? 0) / scale),
    targetFraction: Math.min(1, (target ?? 0) / scale),
  };
}

export interface KpiCard {
  key: "alone" | "sweet" | "peak" | "quality";
  label: string;
  value: string;
  unit: string;
  text: string;
}

export function kpiCards(summary: Summary): KpiCard[] {
  const cfg = summary.config;
  const web = isTimed(cfg);
  const api = isApi(cfg);
  const t = terms(cfg);
  const { rec, max } = deriveRamp(summary);
  const b = summary.baseline;
  const p = summary.probes;
  const alone = splitSecs(web ? b?.e2e_p50 : b?.ttft_p50);
  const peak = max ? throughput(max, cfg) : null;
  const nRight = p?.groups.length ? p.groups.reduce((a, g) => a + g.richtig, 0) : null;
  const firstByte = splitSecs(b?.ttft_p50);

  const sweet: KpiCard = {
    key: "sweet",
    label: "Im selben Augenblick",
    value: rec ? String(rec.concurrency) : "–",
    unit: t.perMinute,
    text: rec
      ? "so viele auf einmal, und alle Ziele werden noch erreicht"
      : summary.ramp
        ? "bei keiner Stufe wurden alle Ziele erreicht"
        : "nicht getestet",
  };

  if (web) {
    return [
      {
        key: "alone",
        label: "Einer allein",
        value: alone.value,
        unit: alone.unit,
        text: b ? t.aloneText : "nicht getestet",
      },
      sweet,
      {
        key: "peak",
        label: "Höchstleistung",
        value: nf(peak, peak != null && peak < 10 ? 1 : 0),
        unit: t.throughputUnit,
        text:
          peak != null
            ? `≈ ${nf(peak * 60, 0)} ${api ? "Anfragen" : isFlow(cfg) ? "Durchläufe" : "Seitenaufrufe"} pro Minute für alle zusammen`
            : "nicht getestet",
      },
      {
        key: "quality",
        label: "Erste Antwort",
        value: firstByte.value,
        unit: firstByte.unit,
        text: b ? t.firstText : "nicht getestet",
      },
    ];
  }
  return [
    {
      key: "alone",
      label: "Einer allein",
      value: alone.value,
      unit: alone.unit,
      text: b ? "bis zum ersten Wort, wenn sonst niemand fragt" : "nicht getestet",
    },
    sweet,
    {
      key: "peak",
      label: "Höchstleistung",
      value: nf(peak, 0),
      unit: "tok/s",
      text: peak != null ? `≈ ${nf(peak / 1.33, 0)} Wörter pro Sekunde für alle zusammen` : "nicht getestet",
    },
    {
      key: "quality",
      label: "Antwortqualität",
      value: nf(p?.load_pct, 0),
      unit: "%",
      text: p
        ? `richtige Antworten unter Last – ohne Last ${nf(p.alone_pct, 0)} % · ${nRight != null ? `${nRight} von ` : ""}${p.n_load} Kontrollfragen`
        : "keine Kontrollfragen gelaufen",
    },
  ];
}

export interface AmpelRow {
  label: string;
  value: string;
  status: Status;
}

const NOT_TESTED = { value: "nicht getestet", status: "none" as const };

function range(lo: string, hi: string): string {
  return lo === hi || hi === "–" ? lo : lo === "–" ? hi : `${lo} – ${hi}`;
}

/** „Alle Ergebnisse auf einen Blick“. */
/**
 * Wie sehr kann man den Zahlen trauen? Wie quality.overall – nur: War allein der Messrechner überlastet
 * („lag“), sind die Werte eher zu schlecht, die Zahl also eine Untergrenze. Das ist „mittel“, nicht „niedrig“ –
 * passend zum Urteil, das dann grün bleibt (llm_stresstest.quality_note).
 */
export function trustLevel(summary: Summary): "hoch" | "mittel" | "niedrig" | null {
  const q = summary.quality;
  if (!q) return null;
  const bad = q.items.filter((i) => i.status === "bad");
  return q.overall === "niedrig" && bad.length > 0 && bad.every((i) => i.key === "lag") ? "mittel" : q.overall;
}

export function ampelRows(summary: Summary): AmpelRow[] {
  const cfg = summary.config;
  const web = isTimed(cfg);
  const api = isApi(cfg);
  const t = terms(cfg);
  const { rec } = deriveRamp(summary);
  const b = summary.baseline;
  const rows: AmpelRow[] = [];

  const loadTone: Status = rec ? "good" : b && meetsSlo(b, cfg) ? "warn" : "bad";
  const first = `${t.wait} bei normaler Last`;
  const second = web ? "Erste Antwort des Servers" : "Lesetempo pro Person";
  if (b || rec) {
    const lo = splitSecs(web ? b?.e2e_p50 : b?.ttft_p50).value;
    const hi = splitSecs(rec ? waitP95(rec, cfg) : null).value;
    rows.push({ label: first, value: `${range(lo, hi)} s`, status: loadTone });
    rows.push({
      label: second,
      value: web
        ? `${range(splitSecs(b?.ttft_p50).value, splitSecs(rec?.ttft_p95).value)} s`
        : `${range(nf(rec?.user_tps_p50, 0), nf(b?.user_tps_p50, 0))} tok/s`,
      status: loadTone,
    });
  } else {
    rows.push({ label: first, ...NOT_TESTED });
    rows.push({ label: second, ...NOT_TESTED });
  }

  if (summary.rate) {
    const ok = summary.capacity.rate_ok;
    rows.push({
      label: "Echter Andrang",
      value: ok ? `bis ${perMinute(ok)} ${t.perMinute}/min` : "Schlange wächst sofort",
      status: ok ? "good" : "bad",
    });
  } else rows.push({ label: "Echter Andrang", ...NOT_TESTED });

  if (!web) {
    const ctx = summary.context;
    if (ctx) {
      const okSteps = ctx.steps.filter((s) => s.single.error_rate === 0);
      const biggest = okSteps[okSteps.length - 1];
      const time = biggest?.single.ttft_p50 ?? null;
      const slow = ctx.limit || time == null || time > 6;
      rows.push({
        label: biggest ? `Lange Texte (${nf(biggest.input_len, 0)} Tokens)` : "Lange Texte",
        value: biggest ? `${secs(time)} bis zum 1. Wort` : "scheitern",
        status: !biggest ? "bad" : slow ? (time != null && time > 20 ? "bad" : "warn") : "good",
      });
    } else rows.push({ label: "Lange Texte", ...NOT_TESTED });
  }

  const spike = summary.spike;
  if (spike) {
    const served = web && !api ? "alle bedient, erholt sich" : "alle beantwortet, erholt sich";
    rows.push({
      label: "Großer Ansturm",
      value: spike.crashed
        ? web
          ? `${t.subject.split(" ")[1]} nicht mehr erreichbar`
          : "Server abgestürzt"
        : spike.recovered === false
          ? "erholt sich nicht vollständig"
          : spike.burst.error_rate > 0
            ? `${errorCount(spike.burst, cfg)} mit Fehler, dann erholt`
            : served,
      status: spike.crashed ? "bad" : spike.recovered === false || spike.burst.error_rate > 0 ? "warn" : "good",
    });
  } else rows.push({ label: "Großer Ansturm", ...NOT_TESTED });

  const soak = summary.soak;
  if (soak) {
    // Einzelne Fehler (bis ERR_OK) sind Netz-Rauschen, ab 1 % ist es ein echtes Problem
    const rate = soak.total.error_rate;
    const failed = rate > ERR_OK;
    // KI-Server: das Tempo fällt ab. Website: die Ladezeit steigt.
    const drop = soak.degradation?.tps_change_pct ?? 0;
    const slower = soak.degradation?.ttft_change_pct ?? 0;
    const tired = web ? slower > 25 : drop < -10;
    const tiredText = web ? `wird langsamer (${signedPct(slower)} ${t.wait})` : `wird müde (${signedPct(drop)})`;
    const errors = errorCount(soak.total, cfg);
    rows.push({
      label: `Ausdauer über ${nf(soak.minutes, soak.minutes < 1 ? 1 : 0)} Minuten`,
      value: failed
        ? `${errors} fehlgeschlagen`
        : tired
          ? tiredText
          : soak.total.errors > 0
            ? `stabil, nur ${errors} fehlgeschlagen`
            : "stabil, kein Abfall",
      status: rate > 0.01 ? "bad" : failed || tired ? "warn" : "good",
    });
  } else rows.push({ label: "Ausdauer", ...NOT_TESTED });

  const control = controlView(summary);
  rows.push(
    control
      ? { label: "Kontrollmessung am Ende", value: control.text, status: control.status }
      : { label: "Kontrollmessung am Ende", ...NOT_TESTED },
  );

  // Hat der Messrechner selbst mitgehalten? Sonst wären die Zeiten zu hoch – zu Unrecht.
  const quality = summary.quality;
  const level = trustLevel(summary);
  if (quality?.items.length && level) {
    const order = ["bad", "warn", "good", "info"];
    const worst = [...quality.items].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status))[0];
    const clean = worst.status === "good" || worst.status === "info";
    rows.push({
      label: "Verlässlichkeit der Messung",
      value: `${level} – ${clean ? "die Messung war sauber" : (worst.short ?? `${worst.title} ${worst.value}`)}`,
      status: ({ hoch: "good", mittel: "warn", niedrig: "bad" } as const)[level],
    });
  }

  return rows;
}

const ECON_DEFAULTS = { hw_price: 4000, server_watts: 200, power_price: 0.3, cloud_price_in: 0.5, cloud_price_out: 1.5 };

export interface CostView {
  own: string;
  cloud: string;
  ownFraction: number;
  cloudFraction: number;
  /** Auslastung beim eigenen Bedarf in Prozent, null ohne Bedarf */
  needPct: number | null;
  savings: string | null;
  saves: boolean;
  breakeven: string;
  /** true, solange noch die mitgelieferten Beispielpreise drinstehen */
  placeholder: boolean;
}

export function costView(summary: Summary): CostView | null {
  const e = summary.economics;
  if (!e) return null;
  const { users, target } = capacityView(summary);
  const top = Math.max(e.own_per_1000 ?? 0, e.cloud_per_1000 ?? 0) || 1;
  const need = users != null && target != null ? Math.min(1, target / users) : null;
  const diff = need != null ? e.cloud_full_month * need - e.own_month : null;
  const roundTo = diff != null && Math.abs(diff) >= 1000 ? 50 : 10;
  const rounded = diff != null ? Math.round(Math.abs(diff) / roundTo) * roundTo : null;
  return {
    own: eur(e.own_per_1000, 2),
    cloud: eur(e.cloud_per_1000, 2),
    ownFraction: (e.own_per_1000 ?? 0) / top,
    cloudFraction: (e.cloud_per_1000 ?? 0) / top,
    needPct: need != null ? Math.round(need * 100) : null,
    savings: rounded != null ? `≈ ${eur(rounded)}` : null,
    saves: (diff ?? 0) >= 0,
    breakeven: e.breakeven_pct == null ? "–" : e.breakeven_pct > 100 ? "nie" : `${nf(e.breakeven_pct, 0)} %`,
    placeholder: (Object.keys(ECON_DEFAULTS) as (keyof typeof ECON_DEFAULTS)[]).every((k) => e[k] === ECON_DEFAULTS[k]),
  };
}

/**
 * Punkte für die Lastkurve je Stufe: Gesamtleistung (tok/s bzw. Seiten/s) und die Zeit,
 * an der das Ziel gemessen wird (Warten aufs erste Wort bzw. Ladezeit).
 */
export function curvePoints(summary: Summary): { c: number; tps: number; ttft: number | null; ok: boolean }[] {
  const cfg = summary.config;
  return deriveRamp(summary).steps.flatMap((s) => {
    const tps = throughput(s, cfg);
    return tps == null ? [] : [{ c: s.concurrency, tps, ttft: waitP95(s, cfg), ok: meetsSlo(s, cfg) }];
  });
}

/** Restzeit der laufenden Stufe im Stufentest (Anlauf + Messfenster). */
export function stageTimer(summary: Summary, samples: Sample[]): { remaining: number; fraction: number } | null {
  const last = lastSample(samples);
  if (!last || !last.phase.startsWith("ramp_")) return null;
  let start = last.t;
  for (let i = samples.length - 1; i >= 0 && samples[i].phase === last.phase; i--) start = samples[i].t;
  const total = summary.config.warmup_seconds + summary.config.level_seconds;
  const elapsed = Math.min(total, last.t - start);
  return { remaining: total - elapsed, fraction: total > 0 ? elapsed / total : 0 };
}
