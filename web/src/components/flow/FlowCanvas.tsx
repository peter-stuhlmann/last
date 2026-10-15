"use client";

import { useState, type ReactNode } from "react";
import { secretName, sentence, type Step } from "@/lib/steps";

export type Row = { id: number; step: Step };

// Kleine Symbole je Art – bewusst schlicht, damit der Ablauf auf einen Blick lesbar bleibt
const PATHS: Record<string, ReactNode> = {
  open: <path d="M12 3a9 9 0 100 18 9 9 0 000-18zm-9 9h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />,
  fill: <path d="M3 7h18v10H3zM7 11h.01M11 11h.01M15 11h.01M7 14h10" />,
  click: <path d="M9 3v8.5l-2-2a1.6 1.6 0 00-2.3 2.3l4.6 5A5 5 0 0013 19h1a5 5 0 005-5v-3a1.5 1.5 0 00-3 0v-1a1.5 1.5 0 00-3 0V9a1.5 1.5 0 00-3 0V3a1 1 0 00-1-1 1 1 0 00-1 1z" />,
  press: <path d="M20 5v6a3 3 0 01-3 3H6m0 0l4-4m-4 4l4 4" />,
  wait: <path d="M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9s8 4 8 9" />,
  raw: <path d="M12 8v5m0 3h.01M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" />,
  note: <path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5" />,
};

function iconFor(step: Step): string {
  if (step.kind === "raw") return step.line.startsWith("#") ? "note" : "raw";
  if (step.kind.startsWith("wait")) return "wait";
  return step.kind in PATHS ? step.kind : "wait";
}

function Icon({ name }: { name: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {PATHS[name]}
    </svg>
  );
}

const TONE: Record<string, string> = {
  open: "bg-white/10 text-white",
  fill: "bg-violet/30 text-lilac",
  click: "bg-cyan/20 text-cyan-soft",
  press: "bg-cyan/20 text-cyan-soft",
  wait: "bg-white/10 text-white/80",
  raw: "bg-amber/25 text-amber-soft",
  note: "bg-white/10 text-white/70",
};

const nodeBtn = "grid size-8 place-items-center rounded-lg text-white/60 hover:bg-white/10 hover:text-white disabled:opacity-30";

function Node({
  row,
  n,
  thumb,
  failed,
  fresh,
  first,
  last,
  onChange,
  onMove,
  onRemove,
}: {
  row: Row;
  n: number;
  thumb?: string;
  failed: boolean;
  fresh: boolean;
  first: boolean;
  last: boolean;
  onChange: (step: Step) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const { step } = row;
  const s = sentence(step);
  const icon = iconFor(step);
  const [editing, setEditing] = useState(false);
  // Ändern lässt sich, was man nicht neu vorführen muss: getippter Text, Wartezeit, Taste
  const editable = (step.kind === "fill" && !secretName(step.text)) || step.kind === "wait_s";
  return (
    <li
      className={`relative flex items-start gap-3 rounded-2xl border bg-ink-2 py-2.5 pl-2.5 pr-2 shadow-[0_6px_18px_rgb(0_0_0/0.35)] ${
        failed ? "border-rose/70" : fresh ? "border-cyan/60" : step.kind === "raw" ? "border-amber/50" : "border-white/10"
      }`}
    >
      <span className={`relative z-10 grid size-9 shrink-0 place-items-center rounded-xl ${TONE[icon]}`}>
        <Icon name={icon} />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-[13px] font-semibold leading-tight">
          <span className="sr-only">Schritt {n}: </span>
          {s.title}
          {s.what && <span className="font-normal text-white/80"> „{s.what}“</span>}
        </p>
        {s.detail && !editing && <p className="mt-0.5 truncate text-xs text-white/60">{s.detail}</p>}
        {failed && <p className="mt-0.5 text-xs text-rose-soft">Hier ist das Vorführen hängen geblieben.</p>}
        {editing && step.kind === "fill" && (
          <input
            aria-label={`Text für Schritt ${n}`}
            value={step.text}
            autoFocus
            onChange={(e) => onChange({ ...step, text: e.target.value })}
            onBlur={() => setEditing(false)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), setEditing(false))}
            className="field mt-1.5 min-h-9 py-1.5 text-sm"
          />
        )}
        {editing && step.kind === "wait_s" && (
          <input
            aria-label={`Sekunden für Schritt ${n}`}
            type="number"
            min="0.5"
            max="60"
            step="0.5"
            value={step.seconds}
            autoFocus
            onChange={(e) => onChange({ ...step, seconds: Math.min(60, Math.max(0.5, Number(e.target.value) || 0.5)) })}
            onBlur={() => setEditing(false)}
            className="field mt-1.5 min-h-9 w-24 py-1.5 text-sm"
          />
        )}
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element -- Ausschnitt kommt als data:-URL vom Backend */}
      {thumb && <img src={thumb} alt="" className="hidden max-h-10 max-w-32 self-center rounded-md border border-white/10 sm:block" />}
      <span className="flex shrink-0 items-center">
        {editable && (
          <button type="button" className={nodeBtn} onClick={() => setEditing((v) => !v)} aria-label={`Schritt ${n} ändern`}>
            ✎
          </button>
        )}
        <button type="button" className={nodeBtn} onClick={() => onMove(-1)} disabled={first} aria-label={`Schritt ${n} nach oben`}>
          ↑
        </button>
        <button type="button" className={nodeBtn} onClick={() => onMove(1)} disabled={last} aria-label={`Schritt ${n} nach unten`}>
          ↓
        </button>
        <button type="button" className={nodeBtn} onClick={onRemove} aria-label={`Schritt ${n} löschen`}>
          ✕
        </button>
      </span>
    </li>
  );
}

function Zone({ tone, title, hint, children }: { tone: "prep" | "measure"; title: string; hint: string; children: ReactNode }) {
  return (
    <section
      aria-label={title}
      className={`rounded-3xl border p-3 ${tone === "measure" ? "border-cyan/35 bg-cyan/[0.05]" : "border-white/10 bg-white/[0.025]"}`}
    >
      <h3 className="mb-2.5 flex flex-wrap items-baseline gap-x-2 px-1 text-sm font-semibold">
        <span className={tone === "measure" ? "text-cyan-soft" : ""}>{title}</span>
        <span className="text-xs font-normal text-white/60">{hint}</span>
      </h3>
      {children}
    </section>
  );
}

/** Die Bausteine einer Zone, verbunden durch eine Linie (wie in n8n, nur ohne Verdrahten). */
function Chain({ children }: { children: ReactNode }) {
  return <ol className="relative grid gap-2 before:absolute before:bottom-4 before:left-[28px] before:top-4 before:w-px before:bg-white/20">{children}</ol>;
}

export function FlowCanvas({
  rows,
  startUrl,
  thumbs,
  failedId,
  freshId,
  onChange,
}: {
  rows: Row[];
  /** Startseite aus dem Formular – erscheint als erster Baustein, wenn der Ablauf nicht selbst mit „öffne“ beginnt */
  startUrl: string | null;
  thumbs: Map<string, string>;
  failedId?: number;
  freshId?: number;
  onChange: (rows: Row[]) => void;
}) {
  const cut = rows.findIndex((r) => r.step.kind === "measure");
  const prep = cut < 0 ? rows : rows.slice(0, cut);
  const measured = cut < 0 ? [] : rows.slice(cut + 1);
  const ownStart = rows[0]?.step.kind === "open";

  const move = (i: number, delta: number) => {
    const next = [...rows];
    const [r] = next.splice(i, 1);
    next.splice(i + delta, 0, r);
    onChange(next);
  };
  // Die Grenze ist der Schritt „messen ab hier“ – früher/später heißt: ihn um eins verschieben
  const shiftBoundary = (delta: number) => move(cut, delta);

  const node = (r: Row, i: number) => (
    <Node
      key={r.id}
      row={r}
      n={i + 1}
      thumb={thumbs.get(formatKey(r.step))}
      failed={r.id === failedId}
      fresh={r.id === freshId}
      first={i === 0}
      last={i === rows.length - 1}
      onChange={(step) => onChange(rows.map((x) => (x.id === r.id ? { ...x, step } : x)))}
      onMove={(d) => move(i, d)}
      onRemove={() => onChange(rows.filter((x) => x.id !== r.id))}
    />
  );

  return (
    <div className="grid gap-2">
      <Zone tone="prep" title="1 · Vorbereitung" hint="wird nicht gemessen – zum Beispiel anmelden">
        <Chain>
          {!ownStart && (
            <li className="relative flex items-center gap-3 rounded-2xl border border-white/10 bg-ink-2 py-2.5 pl-2.5 pr-3">
              <span className={`relative z-10 grid size-9 shrink-0 place-items-center rounded-xl ${TONE.open}`}>
                <Icon name="open" />
              </span>
              <p className="min-w-0 text-[13px] font-semibold">
                Seite öffnen <span className="block truncate font-mono text-xs font-normal text-white/60">{startUrl ?? "Adresse oben eintragen"}</span>
              </p>
            </li>
          )}
          {prep.map((r) => node(r, rows.indexOf(r)))}
        </Chain>
      </Zone>

      {cut >= 0 && (
        <div className="flex items-center justify-center gap-2 text-xs text-white/70">
          <span aria-hidden="true">⏱</span> Ab hier wird gemessen
          <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" onClick={() => shiftBoundary(-1)} disabled={cut === 0}>
            früher
          </button>
          <button
            type="button"
            className="btn btn-ghost min-h-7 px-2 text-[11px]"
            onClick={() => shiftBoundary(1)}
            disabled={cut === rows.length - 1}
          >
            später
          </button>
        </div>
      )}

      <Zone tone="measure" title="2 · Das wird gemessen" hint="unter Last hundertfach gleichzeitig wiederholt">
        {measured.length ? (
          <Chain>{measured.map((r) => node(r, rows.indexOf(r)))}</Chain>
        ) : (
          <p className="rounded-2xl border border-dashed border-cyan/30 px-4 py-3 text-sm text-white/70">
            {cut < 0
              ? "Noch leer. Beim Vorführen an der richtigen Stelle auf „⏱ Ab hier messen“ tippen."
              : "Noch leer. Jetzt vorführen, was gemessen werden soll – zum Beispiel eine Frage stellen."}
          </p>
        )}
      </Zone>
    </div>
  );
}

/** Schlüssel für die Bildausschnitte: dasselbe Element, derselbe Ausschnitt – auch wenn der Text sich ändert. */
export function formatKey(step: Step): string {
  if (step.kind !== "fill" && step.kind !== "click") return "";
  return [step.kind, step.target, step.near ?? "", step.nth ?? ""].join("|");
}
