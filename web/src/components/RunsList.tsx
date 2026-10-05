"use client";

import Link from "next/link";
import { useState } from "react";
import { hostLabel, runLabel } from "@/lib/format";
import type { RunInfo } from "@/lib/types";

const TEST_NAMES: Record<string, string> = {
  baseline: "Einer allein",
  ramp: "Immer mehr",
  rate: "Echter Andrang",
  context: "Lange Texte",
  spike: "Ansturm",
  soak: "Ausdauer",
};

export function RunsList({ runs }: { runs: RunInfo[] }) {
  const [picked, setPicked] = useState<string[]>([]);
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

  return (
    <div className="card p-4 sm:p-7">
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
      <ul className="divide-y divide-white/[0.06]">
        {runs.map((r) => {
          const id = `wahl-${r.name}`;
          const web = r.kind === "web";
          const mismatch = pickedKind != null && (r.kind ?? "llm") !== pickedKind;
          return (
            <li key={r.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
              <input
                id={id}
                type="checkbox"
                checked={picked.includes(r.name)}
                onChange={() => toggle(r.name)}
                disabled={mismatch}
                aria-label={
                  mismatch
                    ? `Lauf vom ${runLabel(r.name)}: passt nicht zur Auswahl (${web ? "Website" : "KI-Server"})`
                    : `Lauf vom ${runLabel(r.name)} zum Vergleich auswählen`
                }
                className="size-5 shrink-0 accent-violet disabled:opacity-30"
              />
              <div className="min-w-0 flex-1 basis-60">
                <Link href={`/laeufe/${r.name}`} className="font-display text-lg font-bold hover:text-cyan">
                  {runLabel(r.name)}
                </Link>
                <p className="truncate font-mono text-xs text-white/65">
                  <span className="mr-2 rounded border border-white/15 px-1.5 py-0.5 font-sans text-[10px] font-semibold uppercase tracking-wide text-white/75">
                    {web ? "Website" : "KI-Server"}
                  </span>
                  {hostLabel(r.base_url)}
                  {r.model ? ` · ${r.model}` : ""}
                </p>
              </div>
              <p className="text-xs text-white/65">{r.tests.map((t) => TEST_NAMES[t] ?? t).join(" · ")}</p>
              <p className="flex gap-2">
                {r.report && (
                  <a
                    href={`/api/runs/${r.name}/report.pptx`}
                    download
                    className="btn btn-ghost"
                    aria-label={`PowerPoint, Lauf ${runLabel(r.name).replace(", ", " um ")}`}
                  >
                    PowerPoint
                  </a>
                )}
                {r.pdf && (
                  <a
                    href={`/api/runs/${r.name}/report.pdf`}
                    download
                    className="btn btn-ghost"
                    aria-label={`PDF, Lauf ${runLabel(r.name).replace(", ", " um ")}`}
                  >
                    PDF
                  </a>
                )}
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
