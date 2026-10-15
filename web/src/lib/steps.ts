// Die Schritt-Sprache der Abläufe – dieselben Muster wie flow_stresstest.PATTERNS im Backend.
// Der Baukasten liest damit den Text in Zeilen und schreibt ihn wieder zurück; das Backend
// prüft beim Start ohnehin noch einmal selbst.

export type StepKind =
  | "open"
  | "fill"
  | "click"
  | "press"
  | "wait_text"
  | "wait_sel"
  | "wait_s"
  | "measure"
  | "wait_first"
  | "wait_done"
  | "wait_quiet";

/** Gibt es ein Feld oder einen Knopf mehrfach: Text in der Nähe („bei“) und/oder die Nummer in Lesereihenfolge. */
export interface Where {
  near?: string;
  nth?: number;
}

export type Step =
  | { kind: "open"; url: string }
  | ({ kind: "fill"; target: string; text: string } & Where)
  | ({ kind: "click"; target: string } & Where)
  | { kind: "wait_text" | "wait_sel" | "wait_first"; target: string }
  | { kind: "press"; key: string }
  | { kind: "wait_s"; seconds: number }
  | { kind: "wait_done"; target: string; quiet: number }
  | { kind: "wait_quiet"; quiet: number }
  | { kind: "measure" }
  // Zeile, die der Baukasten nicht kennt (oder ein Kommentar) – bleibt wörtlich erhalten
  | { kind: "raw"; line: string };

const Q = '"([^"]+)"';
const NUM = "(\\d+(?:[.,]\\d+)?)";
const WHERE = '(?:\\s+bei\\s+"([^"]+)")?(?:\\s*\\(Nr\\.\\s*(\\d{1,3})\\))?';
const PATTERNS: [StepKind, RegExp][] = [
  ["open", /^öffne\s+(\S+)$/i],
  ["fill", new RegExp(`^tippe in\\s+${Q}${WHERE}\\s+(.+)$`, "i")],
  ["click", new RegExp(`^klicke\\s+${Q}${WHERE}$`, "i")],
  ["press", /^drücke\s+(\w+)$/i],
  ["wait_text", new RegExp(`^warte auf text\\s+${Q}$`, "i")],
  ["wait_first", new RegExp(`^warte auf erste antwort in\\s+${Q}$`, "i")],
  ["wait_quiet", new RegExp(`^warte bis die seite ruhig ist(?:\\s*\\(${NUM}\\s*s\\))?$`, "i")],
  ["wait_done", new RegExp(`^warte bis\\s+${Q}\\s+fertig ist(?:\\s*\\(${NUM}\\s*s ruhig\\))?$`, "i")],
  ["wait_sel", new RegExp(`^warte auf\\s+${Q}$`, "i")],
  ["wait_s", new RegExp(`^warte\\s+${NUM}\\s*s$`, "i")],
  ["measure", /^[─\-—=\s]*messen(?:\s+ab\s+hier)?[─\-—=\s]*$/i],
];

export const KEYS = ["Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Space", "Backspace"] as const;
const KEY_NAMES: Record<string, string> = { enter: "Enter", tab: "Tab", escape: "Escape", esc: "Escape" };

const num = (s: string) => Number(s.replace(",", "."));

function where(m: RegExpExecArray): Where {
  const out: Where = {};
  if (m[2]) out.near = m[2];
  if (m[3] && Number(m[3]) >= 1) out.nth = Number(m[3]);
  return out;
}

export function parseLine(raw: string): Step {
  const line = raw.trim();
  if (!line.startsWith("#")) {
    for (const [kind, re] of PATTERNS) {
      const m = re.exec(line);
      if (!m) continue;
      switch (kind) {
        case "open":
          return { kind, url: m[1].replace(/^["']|["']$/g, "") };
        case "fill": {
          let text = m[4].trim();
          if (text.length >= 2 && text.startsWith('"') && text.endsWith('"')) text = text.slice(1, -1);
          return { kind, target: m[1], ...where(m), text };
        }
        case "click":
          return { kind, target: m[1], ...where(m) };
        case "wait_text":
        case "wait_first":
        case "wait_sel":
          return { kind, target: m[1] };
        case "press":
          return { kind, key: KEY_NAMES[m[1].toLowerCase()] ?? m[1] };
        case "wait_done":
          return { kind, target: m[1], quiet: m[2] ? num(m[2]) : 3 };
        case "wait_quiet":
          return { kind, quiet: m[1] ? Math.min(30, num(m[1])) : 2 };
        case "wait_s":
          return { kind, seconds: Math.min(60, num(m[1])) };
        case "measure":
          return { kind };
      }
    }
  }
  return { kind: "raw", line };
}

/** Text → Schritte; leere Zeilen fallen weg, unbekannte bleiben als „raw“ stehen. */
export function parseSteps(text: string): Step[] {
  return text
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map(parseLine);
}

const PLACEHOLDER_ONLY = /^\{[A-Za-z_][\w-]*\}$/;
// Anführungszeichen beenden das Ziel – im Ziel selbst sind sie nicht erlaubt. Nicht kürzen:
// der Baukasten schreibt bei jedem Tastendruck, ein Leerzeichen am Ende muss stehen bleiben.
const target = (t: string) => `"${t.replaceAll('"', "")}"`;
const fmtNum = (n: number) => String(n).replace(".", ",");
const whereText = (w: Where) => (w.near ? ` bei ${target(w.near)}` : "") + (w.nth ? ` (Nr. ${w.nth})` : "");

export function formatStep(step: Step): string {
  switch (step.kind) {
    case "open":
      return `öffne ${step.url}`;
    case "fill":
      return `tippe in ${target(step.target)}${whereText(step)} ${PLACEHOLDER_ONLY.test(step.text) ? step.text : `"${step.text}"`}`;
    case "click":
      return `klicke ${target(step.target)}${whereText(step)}`;
    case "press":
      return `drücke ${step.key}`;
    case "wait_text":
      return `warte auf Text ${target(step.target)}`;
    case "wait_sel":
      return `warte auf ${target(step.target)}`;
    case "wait_s":
      return `warte ${fmtNum(step.seconds)} s`;
    case "wait_first":
      return `warte auf erste Antwort in ${target(step.target)}`;
    case "wait_done":
      return `warte bis ${target(step.target)} fertig ist (${fmtNum(step.quiet)} s ruhig)`;
    case "wait_quiet":
      return `warte bis die Seite ruhig ist (${fmtNum(step.quiet)} s)`;
    case "measure":
      return "messen ab hier";
    case "raw":
      return step.line;
  }
}

export function formatSteps(steps: Step[]): string {
  return steps.map(formatStep).join("\n");
}

/** Die Startseite steht oben im Formular – wer selbst mit „öffne“ anfängt, behält seine Zeile. */
export function withStart(text: string, baseUrl: string): string {
  const own = text.trim();
  if (/^öffne\s/i.test(own)) return own;
  return own ? `öffne ${baseUrl}\n${own}` : `öffne ${baseUrl}`;
}

/** Was am Ablauf noch fehlt, bevor er starten kann – in Worten, für den Hinweis unter dem Baukasten. */
export function stepProblems(steps: Step[]): string[] {
  const out: string[] = [];
  const raw = steps.findIndex((s) => s.kind === "raw" && !s.line.startsWith("#"));
  if (raw >= 0) out.push(`Schritt ${raw + 1} versteht der Test nicht – löschen oder unter „Als Text“ korrigieren.`);
  const empty = steps.findIndex((s) => "target" in s && !s.target.replaceAll('"', "").trim());
  if (empty >= 0) out.push(`Bei Schritt ${empty + 1} fehlt das Ziel.`);
  const measures = steps.filter((s) => s.kind === "measure").length;
  if (measures === 0) out.push("Noch offen, was gemessen wird: beim Vorführen an der richtigen Stelle auf „⏱ Ab hier messen“ tippen.");
  if (measures > 1) out.push("„messen ab hier“ darf nur einmal vorkommen.");
  const last = steps.map((s) => s.kind).lastIndexOf("measure");
  if (measures === 1 && last === steps.length - 1) out.push("Im Bereich „Das wird gemessen“ fehlt noch ein Schritt.");
  return out;
}

const SECRET_ONLY = /^\{([A-Za-z_][\w-]*)\}$/;

/** Name des Platzhalters, wenn der Text nur aus einem besteht – z. B. „passwort“ für {passwort}. */
export function secretName(text: string): string | null {
  return SECRET_ONLY.exec(text)?.[1] ?? null;
}

/** Ein freier Platzhalter-Name: „passwort“, sonst „passwort2“, „passwort3“ … */
export function freePlaceholder(base: string, used: string[]): string {
  const clean = base.replace(/[^A-Za-z0-9_]/g, "").replace(/^[^A-Za-z]+/, "").slice(0, 24) || "wert";
  if (!used.includes(clean)) return clean;
  for (let i = 2; ; i++) if (!used.includes(`${clean}${i}`)) return `${clean}${i}`;
}

export interface Sentence {
  /** kurze Überschrift des Bausteins, z. B. „Klicken“ */
  title: string;
  /** worauf, z. B. „Anmelden“ */
  what?: string;
  /** Zusatz in Worten, z. B. „bei Bestellung 4711“ */
  detail?: string;
}

const whereWords = (w: Where) => [w.near ? `bei „${w.near}“` : "", w.nth ? `der ${w.nth}. auf der Seite` : ""].filter(Boolean).join(", ");

/** Der Schritt in Alltagssprache – für die Bausteine im Ablauf. */
export function sentence(step: Step): Sentence {
  switch (step.kind) {
    case "open":
      return { title: "Seite öffnen", what: step.url };
    case "fill": {
      const secret = secretName(step.text);
      return {
        title: "Eingeben",
        what: step.target,
        detail: [secret ? `Zugangsdaten {${secret}}` : `„${step.text}“`, whereWords(step)].filter(Boolean).join(" · "),
      };
    }
    case "click":
      return { title: "Klicken", what: step.target, detail: whereWords(step) || undefined };
    case "press":
      return { title: "Taste drücken", what: step.key === "Enter" ? "Enter ↵" : step.key };
    case "wait_quiet":
      return { title: "Warten, bis die Seite fertig ist", detail: `fertig, wenn sich ${fmtNum(step.quiet)} s nichts mehr ändert` };
    case "wait_text":
      return { title: "Warten auf Text", what: step.target };
    case "wait_sel":
      return { title: "Warten auf", what: step.target };
    case "wait_first":
      return { title: "Warten auf erste Antwort", what: step.target };
    case "wait_done":
      return { title: "Warten, bis die Antwort fertig ist", what: step.target };
    case "wait_s":
      return { title: "Warten", what: `${fmtNum(step.seconds)} Sekunden` };
    case "measure":
      return { title: "Ab hier wird gemessen" };
    case "raw":
      return step.line.startsWith("#") ? { title: "Notiz", what: step.line.slice(1).trim() } : { title: "Unbekannter Schritt", what: step.line };
  }
}
