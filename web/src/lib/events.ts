import type { EventMessage, RunState, Sample, Summary } from "./types";

export interface LiveState {
  /** false, bis die erste Nachricht des Servers da ist */
  connected: boolean;
  /** true, solange die Verbindung zum Ereignis-Strom gerade weg ist (der letzte Stand bleibt stehen) */
  offline: boolean;
  run: string;
  state: RunState;
  error: string | null;
  report: boolean;
  pdf: boolean;
  summary: Summary | null;
  samples: Sample[];
  logs: string[];
}

export const initialLive: LiveState = {
  connected: false,
  offline: false,
  run: "",
  state: "idle",
  error: null,
  report: false,
  pdf: false,
  summary: null,
  samples: [],
  logs: [],
};

// Obergrenzen, damit der Browser auch bei stundenlangen Läufen nicht voll läuft.
const MAX_LOGS = 400;
const MAX_SAMPLES = 4000;

function tail<T>(items: T[], max: number): T[] {
  return items.length > max ? items.slice(items.length - max) : items;
}

/**
 * Kurz nach dem Start schickt das Backend nur config und meta; Kapazität, Urteil usw.
 * kommen erst mit den ersten Messwerten. Hier werden die Lücken neutral gefüllt.
 */
export function normalizeSummary(summary: Summary | null): Summary | null {
  if (!summary) return null;
  return {
    ...summary,
    meta: summary.meta ?? {},
    capacity: summary.capacity ?? { think_time: summary.config.think_time ?? 60, users: null, source: null },
    probes: summary.probes ?? null,
    economics: summary.economics ?? null,
    verdict: summary.verdict ?? { status: "warn", headline: "", reasons: [] },
  };
}

/** Nachrichten des Servers plus das, was der Browser selbst feststellt. */
export type LiveAction = EventMessage | { type: "offline" };

export function reduceLive(s: LiveState, msg: LiveAction): LiveState {
  switch (msg.type) {
    case "offline":
      return { ...s, offline: true };
    case "reset":
      return { ...initialLive, connected: true, run: msg.run };
    case "log":
      return { ...s, connected: true, offline: false, logs: tail([...s.logs, ...msg.lines], MAX_LOGS) };
    case "samples":
      return { ...s, connected: true, offline: false, samples: tail([...s.samples, ...msg.samples], MAX_SAMPLES) };
    case "state":
      return {
        ...s,
        connected: true,
        offline: false,
        run: msg.run,
        state: msg.state,
        error: msg.error,
        report: msg.report,
        pdf: msg.pdf,
        summary: normalizeSummary(msg.summary),
      };
    default:
      return s;
  }
}

export interface LogLine {
  time: string;
  text: string;
  kind: "heading" | "stage" | "good" | "bad" | "plain";
}

export function parseLogLine(line: string): LogLine {
  const m = /^\[(\d{2}:\d{2}:\d{2})\]\s?(.*)$/.exec(line);
  const time = m?.[1] ?? "";
  const text = (m ? m[2] : line).trim();
  const kind = text.startsWith("━━")
    ? "heading"
    : text.startsWith("✓")
      ? "good"
      : text.startsWith("✗")
        ? "bad"
        : /^\S+ (gleichzeitig|Fragen pro Minute)/.test(text)
          ? "stage"
          : "plain";
  return { time, text, kind };
}
