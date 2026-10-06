"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";
import { hostLabel, runLabel } from "@/lib/format";
import { filterRuns } from "@/lib/trend";
import type { RunInfo, RunKind } from "@/lib/types";
import { ConfirmDialog } from "./ConfirmDialog";

const TEST_NAMES: Record<string, string> = {
  baseline: "Einer allein",
  ramp: "Immer mehr",
  rate: "Echter Andrang",
  context: "Lange Texte",
  spike: "Ansturm",
  soak: "Ausdauer",
};

const KIND_LABEL: Record<RunKind, string> = { llm: "KI-Server", web: "Website", api: "HTTP-API", flow: "Ablauf" };

export function RunsList({ runs, deleted }: { runs: RunInfo[]; deleted?: string | null }) {
  const router = useRouter();
  const id = useId();
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [kind, setKind] = useState<RunKind | null>(null);
  const [toDelete, setToDelete] = useState<RunInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gone, setGone] = useState<string | null>(deleted ?? null);
  const deleteButtons = useRef(new Map<string, HTMLButtonElement>());
  const ready = picked.length >= 2;
  const label = ready ? `${picked.length} Läufe vergleichen (PowerPoint)` : "Zwei Läufe ankreuzen zum Vergleichen";

  if (runs.length === 0) {
    return (
      <p className="card p-8 text-center text-white/75">
        Noch keine Läufe.{" "}
        <Link href="/" className="font-semibold text-cyan underline underline-offset-4">
          Ersten Test starten
        </Link>
      </p>
    );
  }

  const toggle = (name: string) => setPicked((p) => (p.includes(name) ? p.filter((n) => n !== name) : [...p, name]));
  // Website- und KI-Server-Läufe messen Verschiedenes: Der erste Haken legt die Art fest.
  const kindOf = (name: string) => runs.find((r) => r.name === name)?.kind ?? "llm";
  const pickedKind = picked.length ? kindOf(picked[0]) : null;
  const shown = filterRuns(runs, { text, kind });
  const kinds = (["llm", "web", "api", "flow"] as RunKind[]).filter((k) => runs.some((r) => (r.kind ?? "llm") === k));

  async function remove(r: RunInfo) {
    setToDelete(null);
    setError(null);
    try {
      const res = await fetch(`/api/runs/${r.name}`, { method: "DELETE", headers: { "content-type": "application/json" }, body: "{}" });
      const data = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) {
        setError(data.error ?? "Löschen fehlgeschlagen.");
        return;
      }
      setGone(r.name);
      setPicked((p) => p.filter((n) => n !== r.name));
      router.refresh();
    } catch {
      setError("Keine Verbindung zur Oberfläche. Läuft der Container noch?");
    }
  }

  return (
    <div className="card p-4 sm:p-7">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label htmlFor={`${id}-suche`} className="sr-only">
          Läufe durchsuchen
        </label>
        <input
          id={`${id}-suche`}
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Suchen: Titel, #tag, Adresse, Modell, Datum"
          autoComplete="off"
          className="field min-w-0 flex-1 basis-64 py-2 text-sm"
        />
        {kinds.length > 1 && (
          <div role="group" aria-label="Art" className="flex flex-wrap gap-1.5">
            {[null, ...kinds].map((k) => (
              <button
                key={k ?? "alle"}
                type="button"
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
                className={`btn py-1.5 text-xs ${kind === k ? "btn-primary" : "btn-ghost"}`}
              >
                {k ? KIND_LABEL[k] : "Alle"}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-white/70">
          Der älteste angekreuzte Lauf ist die Referenz. Verglichen werden nur Läufe gleicher Art – Websites mit
          Websites, KI-Server mit KI-Servern.
        </p>
        {ready ? (
          <a
            href={`/api/compare?runs=${encodeURIComponent(
              runs
                .filter((r) => picked.includes(r.name))
                .map((r) => r.name)
                .join(","),
            )}`}
            download
            className="btn btn-primary"
          >
            {label}
          </a>
        ) : (
          <a role="link" aria-disabled="true" className="btn btn-ghost">
            {label}
          </a>
        )}
      </div>

      <p role="status" aria-live="polite" className="min-h-5 text-xs text-mint-soft">
        {gone ? `Lauf vom ${runLabel(gone)} liegt im Papierkorb (results/.papierkorb) – 7 Tage lang zurückholbar.` : ""}
      </p>
      {error && (
        <p role="alert" className="mb-2 text-sm text-rose-soft">
          {error}
        </p>
      )}

      {shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-white/65">Kein Lauf passt zur Suche.</p>
      ) : (
        <ul className="divide-y divide-white/[0.06]">
          {shown.map((r) => {
            const cid = `wahl-${r.name}`;
            const kindLabel = KIND_LABEL[r.kind ?? "llm"];
            const mismatch = pickedKind != null && (r.kind ?? "llm") !== pickedKind;
            const when = runLabel(r.name);
            return (
              <li key={r.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
                <input
                  id={cid}
                  type="checkbox"
                  checked={picked.includes(r.name)}
                  onChange={() => toggle(r.name)}
                  disabled={mismatch}
                  aria-label={mismatch ? `Lauf vom ${when}: passt nicht zur Auswahl (${kindLabel})` : `Lauf vom ${when} zum Vergleich auswählen`}
                  className="size-5 shrink-0 accent-violet disabled:opacity-30"
                />
                <div className="min-w-0 flex-1 basis-60">
                  <Link href={`/laeufe/${r.name}`} className="font-display text-lg font-bold hover:text-cyan">
                    {r.pinned && (
                      <span aria-label="angepinnt" role="img" className="mr-1.5 text-sm">
                        📌
                      </span>
                    )}
                    {r.title ?? when}
                  </Link>
                  <p className="truncate font-mono text-xs text-white/65">
                    <span className="mr-2 rounded border border-white/15 px-1.5 py-0.5 font-sans text-[10px] font-semibold uppercase tracking-wide text-white/75">
                      {kindLabel}
                    </span>
                    {r.title ? `${when} · ` : ""}
                    {hostLabel(r.base_url)}
                    {r.model ? ` · ${r.model}` : ""}
                  </p>
                  {r.tags.length > 0 && (
                    <p className="mt-1 flex flex-wrap gap-1.5">
                      {r.tags.map((t) => (
                        <button
                          key={t}
                          type="button"
                          onClick={() => setText(`#${t}`)}
                          className="rounded-full border border-white/15 bg-white/[0.05] px-2 py-0.5 font-mono text-[11px] hover:border-cyan"
                          aria-label={`Nach Tag ${t} filtern`}
                        >
                          #{t}
                        </button>
                      ))}
                    </p>
                  )}
                </div>
                <p className="text-xs text-white/65">{r.tests.map((t) => TEST_NAMES[t] ?? t).join(" · ")}</p>
                <p className="flex gap-2">
                  {r.report && (
                    <a href={`/api/runs/${r.name}/report.pptx`} download className="btn btn-ghost" aria-label={`PowerPoint, Lauf ${when.replace(", ", " um ")}`}>
                      PowerPoint
                    </a>
                  )}
                  {r.pdf && (
                    <a href={`/api/runs/${r.name}/report.pdf`} download className="btn btn-ghost" aria-label={`PDF, Lauf ${when.replace(", ", " um ")}`}>
                      PDF
                    </a>
                  )}
                  <button
                    ref={(el) => {
                      if (el) deleteButtons.current.set(r.name, el);
                      else deleteButtons.current.delete(r.name);
                    }}
                    type="button"
                    className="btn btn-ghost text-rose-soft"
                    aria-label={`Lauf ${r.title ?? `vom ${when}`} löschen`}
                    onClick={() => setToDelete(r)}
                  >
                    <span aria-hidden="true">🗑</span>
                  </button>
                </p>
              </li>
            );
          })}
        </ul>
      )}

      {toDelete && (
        <ConfirmDialog
          id={`${id}-del`}
          title={`„${toDelete.title ?? `Lauf vom ${runLabel(toDelete.name)}`}“ löschen?`}
          text="Er wandert in den Papierkorb (results/.papierkorb) und wird nach 7 Tagen endgültig entfernt."
          confirmLabel="In den Papierkorb"
          onConfirm={() => void remove(toDelete)}
          onClose={() => {
            const name = toDelete.name;
            setToDelete(null);
            deleteButtons.current.get(name)?.focus();
          }}
        />
      )}
    </div>
  );
}
