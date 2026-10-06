"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { nf, runLabel, secs } from "@/lib/format";
import { trendGroups, trendText, type TrendGroup } from "@/lib/trend";
import type { RunInfo } from "@/lib/types";

const W = 640;
const H = 220;
const X0 = 48;
const X1 = W - 16;
const Y0 = 16;
const Y1 = H - 36;

const DOT: Record<string, string> = { good: "#34D399", warn: "#FBBF24", bad: "#F43F5E" };

function scale(values: number[], max: number): (v: number) => number {
  return (v) => Y1 - (max > 0 ? v / max : 0) * (Y1 - Y0);
}

function Chart({ g }: { g: TrendGroup }) {
  const runs = g.runs;
  const n = runs.length;
  const x = (i: number) => (n === 1 ? (X0 + X1) / 2 : X0 + (i / (n - 1)) * (X1 - X0));
  const users = runs.map((r) => r.users ?? 0);
  const target = Math.max(0, ...runs.map((r) => r.target_users ?? 0));
  const maxU = Math.max(...users, target, 1) * 1.15;
  const yU = scale(users, maxU);
  const alone = runs.map((r) => r.alone ?? null);
  const maxA = Math.max(...alone.map((a) => a ?? 0), 0.001) * 1.3;
  const yA = scale([], maxA);
  const ticks = [0, 0.5, 1].map((f) => Math.round(maxU * f));
  const path = users.map((u, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${yU(u).toFixed(1)}`).join(" ");
  const alonePath = alone
    .map((a, i) => (a == null ? null : `${x(i).toFixed(1)} ${yA(a).toFixed(1)}`))
    .filter((p): p is string => p != null)
    .map((p, i) => `${i ? "L" : "M"}${p}`)
    .join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Verlauf der Kapazität in ${g.unit} über ${n} Läufe`} className="h-auto w-full">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={X0} x2={X1} y1={yU(t)} y2={yU(t)} stroke="#fff" strokeOpacity="0.08" />
          <text x={X0 - 6} y={yU(t) + 4} textAnchor="end" fontSize="10" fill="#fff" fillOpacity="0.55" fontFamily="JetBrains Mono, monospace">
            {nf(t, 0)}
          </text>
        </g>
      ))}
      {target > 0 && (
        <>
          <line x1={X0} x2={X1} y1={yU(target)} y2={yU(target)} stroke="#fff" strokeOpacity="0.5" strokeDasharray="4 6" />
          <text x={X1} y={yU(target) - 5} textAnchor="end" fontSize="10" fill="#fff" fillOpacity="0.7" fontFamily="JetBrains Mono, monospace">
            Bedarf {nf(target, 0)}
          </text>
        </>
      )}
      {alonePath && <path d={alonePath} fill="none" stroke="#F9A8D4" strokeOpacity="0.7" strokeWidth="1.5" strokeDasharray="2 4" />}
      <path d={path} fill="none" stroke="#22D3EE" strokeWidth="2.5" strokeLinejoin="round" />
      {runs.map((r, i) => (
        <g key={r.name}>
          <circle cx={x(i)} cy={yU(users[i])} r={r.pinned ? 7 : 5} fill={DOT[r.status ?? ""] ?? "#94A3B8"} stroke="#0a0b14" strokeWidth="2">
            <title>
              {`${r.title ?? runLabel(r.name)}: ${nf(users[i], 0)} ${g.unit}${alone[i] != null ? `, ${g.wait} ohne Andrang ${secs(alone[i])}` : ""}`}
            </title>
          </circle>
          <text x={x(i)} y={H - 18} textAnchor="middle" fontSize="10" fill="#fff" fillOpacity="0.6" fontFamily="JetBrains Mono, monospace">
            {runLabel(r.name).split(",")[0].slice(0, 6)}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Verlauf über die Zeit: Kapazität (und Zeit ohne Andrang) aller Läufe gleicher Art und Adresse. */
export function Trend({ runs }: { runs: RunInfo[] }) {
  const id = useId();
  const groups = trendGroups(runs).filter((g) => g.runs.length >= 2);
  const [key, setKey] = useState<string>(groups[0]?.key ?? "");
  const g = groups.find((x) => x.key === key) ?? groups[0];
  if (!g) return null;

  return (
    <section aria-labelledby={`${id}-h`} className="card mb-6 p-5 sm:p-7">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id={`${id}-h`} className="font-display text-xl font-bold">
          Verlauf
        </h2>
        {groups.length > 1 ? (
          <>
            <label htmlFor={`${id}-g`} className="sr-only">
              Ziel wählen
            </label>
            <select id={`${id}-g`} value={g.key} onChange={(e) => setKey(e.target.value)} className="field w-auto py-1.5 text-sm">
              {groups.map((x) => (
                <option key={x.key} value={x.key}>
                  {x.label} ({x.runs.length})
                </option>
              ))}
            </select>
          </>
        ) : (
          <p className="font-mono text-xs text-white/65">
            {g.label} · {g.runs.length} Läufe
          </p>
        )}
      </div>
      <Chart g={g} />
      <p className="mt-2 flex flex-wrap gap-x-5 font-mono text-[11px] text-white/60">
        <span>
          <span aria-hidden="true" className="mr-1.5 inline-block h-0.5 w-5 translate-y-[-3px] bg-cyan" />
          Kapazität in {g.unit}
        </span>
        <span>
          <span aria-hidden="true" className="mr-1.5 inline-block h-0.5 w-5 translate-y-[-3px] border-t border-dashed border-pink" />
          {g.wait} ohne Andrang (eigene Skala)
        </span>
        <span>Punkte: Urteil des Laufs</span>
      </p>
      <p className="mt-3 text-sm text-white/85">{trendText(g)}</p>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {g.runs.map((r) => (
          <li key={r.name}>
            <Link href={`/laeufe/${r.name}`} className="text-cyan hover:underline">
              {r.title ?? runLabel(r.name)}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
