"use client";

import { useEffect, useRef, useState } from "react";
import { formatSteps, parseLine, parseSteps, stepProblems } from "@/lib/steps";
import { FlowCanvas, formatKey, type Row } from "./FlowCanvas";
import { LiveRecorder } from "./LiveRecorder";
import type { SiteAuth } from "@/lib/validation";

let lastId = 0;
const toRows = (text: string): Row[] => parseSteps(text).map((step) => ({ id: ++lastId, step }));
const isNote = (r: Row) => r.step.kind === "raw" && r.step.line.startsWith("#");

export function FlowSteps({
  value,
  onChange,
  baseUrl,
  secrets,
  siteAuth,
  onSecret,
}: {
  value: string;
  onChange: (text: string) => void;
  /** geprüfte Adresse der Startseite oder null */
  baseUrl: string | null;
  /** Werte der Platzhalter – das Vorführen braucht sie, um sich anzumelden */
  secrets: Record<string, string>;
  /** Seitenschutz (.htaccess) – das Vorführen meldet sich damit an */
  siteAuth?: SiteAuth | null;
  onSecret: (name: string, value: string) => void;
}) {
  const [mode, setMode] = useState<"visual" | "text">("visual");
  // Die Bausteine haben feste Schlüssel; der Text ist die gemeinsame Wahrheit. Ändert er sich von außen
  // (Textmodus, gemerkte Eingabe), werden die Bausteine neu gelesen.
  const [rows, setRows] = useState<Row[]>(() => toRows(value));
  const [emitted, setEmitted] = useState(value);
  const rowsRef = useRef(rows);
  const [thumbs, setThumbs] = useState<Map<string, string>>(() => new Map());
  const [recording, setRecording] = useState(false);
  const [failedId, setFailedId] = useState<number | undefined>();
  const [freshId, setFreshId] = useState<number | undefined>();
  const [hint, setHint] = useState<string | null>(null);
  const opener = useRef<HTMLButtonElement>(null);
  if (value !== emitted) {
    setEmitted(value);
    setRows(toRows(value));
  }
  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  function update(next: Row[]): string {
    const text = formatSteps(next.map((r) => r.step));
    rowsRef.current = next;
    setRows(next);
    setEmitted(text);
    onChange(text);
    return text;
  }

  // Das Vorführen hängt Schritte an – über die Ref, damit zwei Antworten kurz hintereinander nichts verlieren
  function append(lines: string[], thumb: string | null): string {
    const added = lines.map((line) => ({ id: ++lastId, step: parseLine(line) }));
    const withThumb = added.find((r) => formatKey(r.step));
    if (thumb && withThumb) setThumbs((m) => new Map(m).set(formatKey(withThumb.step), thumb));
    setFreshId(added[0]?.id);
    return update([...rowsRef.current, ...added]);
  }

  const executed = () => rowsRef.current.filter((r) => !isNote(r));

  function truncate(executedIndex: number): string {
    const cut = executed()[executedIndex];
    return update(rowsRef.current.slice(0, cut ? rowsRef.current.indexOf(cut) : rowsRef.current.length));
  }

  function openRecorder() {
    if (!baseUrl) {
      setHint("Erst oben die Adresse der Startseite eintragen.");
      return;
    }
    setHint(null);
    setRecording(true);
  }

  const problems = rows.length ? stepProblems(rows.map((r) => r.step)) : [];
  const canvas = <FlowCanvas rows={rows} startUrl={baseUrl} thumbs={thumbs} failedId={failedId} freshId={freshId} onChange={update} />;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span id="flow_steps-titel" className="text-xs font-medium text-white/70">
          Die Schritte
        </span>
        <div role="group" aria-label="Schritte anzeigen als" className="flex rounded-lg border border-white/12 bg-white/[0.04] p-0.5">
          {(["visual", "text"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1 text-xs font-semibold ${mode === m ? "bg-violet/40 text-white" : "text-white/70 hover:text-white"}`}
            >
              {m === "visual" ? "Grafisch" : "Als Text"}
            </button>
          ))}
        </div>
      </div>

      <button
        ref={opener}
        type="button"
        onClick={openRecorder}
        className="mb-3 flex w-full items-center gap-4 rounded-2xl border border-cyan/40 bg-gradient-to-r from-violet/25 to-cyan/15 px-5 py-4 text-left transition hover:brightness-110"
      >
        <span aria-hidden="true" className="grid size-11 shrink-0 place-items-center rounded-full bg-cyan/25 text-lg text-cyan">
          ▶
        </span>
        <span>
          <span className="block font-display text-lg font-bold">{rows.length ? "Weiter vorführen" : "Ablauf vorführen"}</span>
          <span className="block text-xs text-white/70">
            Die Seite öffnet sich, du klickst dich durch – wie ein Mensch. Daraus entstehen die Schritte von selbst.
          </span>
        </span>
      </button>
      {hint && (
        <p role="alert" className="mb-3 text-sm text-rose-soft">
          {hint}
        </p>
      )}

      {mode === "text" ? (
        <textarea
          id="flow_steps"
          name="flow_steps"
          rows={9}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          placeholder={'tippe in "E-Mail" {email}\nklicke "Anmelden"\nmessen ab hier\n…'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-labelledby="flow_steps-titel"
          className="field font-mono text-[13px] leading-relaxed"
        />
      ) : (
        canvas
      )}

      {problems.length > 0 && (
        <ul className="mt-2 grid gap-1 text-xs text-amber-soft">
          {problems.map((p) => (
            <li key={p}>• {p}</li>
          ))}
        </ul>
      )}

      {recording && baseUrl && (
        <LiveRecorder
          text={value}
          baseUrl={baseUrl}
          secrets={secrets}
          siteAuth={siteAuth}
          sidebar={canvas}
          onAppend={append}
          onTruncate={truncate}
          onSecret={onSecret}
          onFailed={(i) => setFailedId(i === null ? undefined : executed()[i]?.id)}
          onClose={() => {
            setRecording(false);
            setFreshId(undefined);
            opener.current?.focus();
          }}
        />
      )}
    </div>
  );
}
