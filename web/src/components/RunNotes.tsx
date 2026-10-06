"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";
import { runLabel } from "@/lib/format";
import type { RunNotes as Notes } from "@/lib/types";
import { MAX_NOTE, MAX_TAGS, MAX_TITLE, TAG_RE } from "@/lib/validation";
import { ConfirmDialog } from "./ConfirmDialog";

const EMPTY: Notes = { title: null, tags: [], note: "", pinned: false };

async function send(path: string, method: "PUT" | "DELETE", body?: unknown): Promise<{ ok: boolean; data: Record<string, unknown> }> {
  try {
    const res = await fetch(path, {
      method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    return { ok: res.ok, data: (await res.json().catch(() => ({}))) as Record<string, unknown> };
  } catch {
    return { ok: false, data: { error: "Keine Verbindung zur Oberfläche. Läuft der Container noch?" } };
  }
}

/** Was Menschen einem Lauf mitgeben: Titel, Tags, Notiz, Pin – und das Löschen in den Papierkorb. */
export function RunNotes({ name, initial, allTags = [] }: { name: string; initial?: Partial<Notes> | null; allTags?: string[] }) {
  const router = useRouter();
  const id = useId();
  const [notes, setNotes] = useState<Notes>({ ...EMPTY, ...initial });
  const [title, setTitle] = useState(notes.title ?? "");
  const [note, setNote] = useState(notes.note);
  const [tagInput, setTagInput] = useState("");
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);

  async function save(next: Notes) {
    setError(null);
    setBusy(true);
    const { ok, data } = await send(`/api/runs/${name}/notes`, "PUT", next);
    setBusy(false);
    if (!ok) {
      setError(String(data.error ?? "Speichern fehlgeschlagen."));
      setStatus("");
      return false;
    }
    setNotes(next);
    setStatus("Gespeichert");
    router.refresh();
    return true;
  }

  async function saveText() {
    const ok = await save({ ...notes, title: title.trim() || null, note: note.trim() });
    if (ok) setEditing(false);
  }

  function addTag(raw: string) {
    const tag = raw.trim().toLowerCase().replace(/^#/, "");
    if (!tag) return;
    if (!TAG_RE.test(tag)) return setError("Tag: bis 24 Zeichen aus Buchstaben, Ziffern, Punkt, Strich.");
    if (notes.tags.includes(tag)) return setTagInput("");
    if (notes.tags.length >= MAX_TAGS) return setError(`Höchstens ${MAX_TAGS} Tags.`);
    setTagInput("");
    void save({ ...notes, tags: [...notes.tags, tag] });
  }

  async function remove() {
    setConfirm(false);
    setBusy(true);
    const { ok, data } = await send(`/api/runs/${name}`, "DELETE");
    if (!ok) {
      setBusy(false);
      setError(String(data.error ?? "Löschen fehlgeschlagen."));
      deleteButton.current?.focus();
      return;
    }
    router.push(`/laeufe?geloescht=${encodeURIComponent(name)}`);
    router.refresh();
  }

  const heading = notes.title ?? `Lauf vom ${runLabel(name)}`;

  return (
    <section aria-labelledby={`${id}-h`} className="card p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {editing ? (
            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void saveText();
              }}
            >
              <div>
                <label htmlFor={`${id}-titel`} className="mb-1 block text-xs font-medium text-white/70">
                  Titel
                </label>
                <input
                  id={`${id}-titel`}
                  value={title}
                  maxLength={MAX_TITLE}
                  autoComplete="off"
                  placeholder="z. B. Vor dem Redis-Cache"
                  onChange={(e) => setTitle(e.target.value)}
                  className="field font-display text-lg font-bold"
                />
              </div>
              <div>
                <label htmlFor={`${id}-notiz`} className="mb-1 block text-xs font-medium text-white/70">
                  Notiz
                </label>
                <textarea
                  id={`${id}-notiz`}
                  value={note}
                  rows={3}
                  maxLength={MAX_NOTE}
                  placeholder="Was war anders? Was wurde geändert?"
                  onChange={(e) => setNote(e.target.value)}
                  className="field text-sm"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="submit" disabled={busy} className="btn btn-primary">
                  Speichern
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => {
                    setTitle(notes.title ?? "");
                    setNote(notes.note);
                    setEditing(false);
                  }}
                >
                  Verwerfen
                </button>
              </div>
            </form>
          ) : (
            <>
              <h2 id={`${id}-h`} className="font-display text-2xl font-bold tracking-[-0.02em]">
                {heading}
              </h2>
              {notes.title && <p className="mt-0.5 font-mono text-xs text-white/55">Lauf vom {runLabel(name)}</p>}
              {notes.note ? (
                <p className="mt-2 max-w-2xl whitespace-pre-line text-sm text-white/80">{notes.note}</p>
              ) : (
                <p className="mt-2 text-sm text-white/55">Noch keine Notiz – was war bei diesem Lauf anders?</p>
              )}
              <button type="button" className="btn btn-ghost mt-3" onClick={() => setEditing(true)}>
                Titel und Notiz bearbeiten
              </button>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            aria-pressed={notes.pinned}
            disabled={busy}
            className={`btn ${notes.pinned ? "btn-primary" : "btn-ghost"}`}
            onClick={() => void save({ ...notes, pinned: !notes.pinned })}
          >
            <span aria-hidden="true">📌</span> {notes.pinned ? "Angepinnt" : "Anpinnen"}
          </button>
          <button ref={deleteButton} type="button" disabled={busy} className="btn btn-danger" onClick={() => setConfirm(true)}>
            Lauf löschen
          </button>
        </div>
      </div>

      <div className="mt-4">
        <p id={`${id}-tags-l`} className="mb-1.5 text-xs font-medium text-white/70">
          Tags
        </p>
        <ul aria-labelledby={`${id}-tags-l`} className="flex flex-wrap items-center gap-2">
          {notes.tags.map((t) => (
            <li key={t} className="flex items-center gap-1 rounded-full border border-white/15 bg-white/[0.05] py-1 pl-3 pr-1 font-mono text-xs">
              #{t}
              <button
                type="button"
                aria-label={`Tag ${t} entfernen`}
                disabled={busy}
                className="grid size-6 place-items-center rounded-full hover:bg-white/15"
                onClick={() => void save({ ...notes, tags: notes.tags.filter((x) => x !== t) })}
              >
                ×
              </button>
            </li>
          ))}
          <li>
            <label htmlFor={`${id}-tag`} className="sr-only">
              Tag hinzufügen
            </label>
            <input
              id={`${id}-tag`}
              list={`${id}-tagliste`}
              value={tagInput}
              autoComplete="off"
              placeholder="+ Tag, Enter"
              maxLength={25}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  addTag(tagInput);
                }
              }}
              onBlur={() => tagInput && addTag(tagInput)}
              className="w-32 rounded-full border border-dashed border-white/20 bg-transparent px-3 py-1 font-mono text-xs placeholder:text-white/45 focus:border-cyan focus:outline-none"
            />
            <datalist id={`${id}-tagliste`}>
              {allTags
                .filter((t) => !notes.tags.includes(t))
                .map((t) => (
                  <option key={t} value={t} />
                ))}
            </datalist>
          </li>
        </ul>
      </div>

      <p role="status" aria-live="polite" className="mt-3 min-h-5 font-mono text-xs text-mint-soft">
        {status}
      </p>
      {error && (
        <p role="alert" className="mt-1 text-sm text-rose-soft">
          {error}
        </p>
      )}

      {confirm && (
        <ConfirmDialog
          id={`${id}-del`}
          title="Diesen Lauf löschen?"
          text="Er wandert in den Papierkorb (results/.papierkorb) und wird nach 7 Tagen endgültig entfernt. Bis dahin lässt er sich von Hand zurückholen."
          confirmLabel="In den Papierkorb"
          onConfirm={() => void remove()}
          onClose={() => {
            setConfirm(false);
            deleteButton.current?.focus();
          }}
        />
      )}
    </section>
  );
}
