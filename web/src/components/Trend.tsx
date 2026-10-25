"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { Select } from "@/components/Select";
import { nf, runLabel, secs } from "@/lib/format";
import { niceStep } from "@/lib/scale";
import { trendGroups, trendText, type TrendGroup } from "@/lib/trend";
import type { RunInfo } from "@/lib/types";

const W = 640;
const H = 220;
const X0 = 48;
const X1 = W - 16;
const Y0 = 16;
const Y1 = H - 36;

const DOT: Record<string, string> = { good: "#34D399", warn: "#FBBF24", bad: "#F43F5E" };

function Chart({ g }: { g: TrendGroup }) {
  const runs = g.runs;
  const n = runs.length;
  // Punkte etwas vom Rand abrücken, damit Datum und Uhrzeit darunter ganz zu lesen sind
  const x = (i: number) => (n === 1 ? (X0 + X1) / 2 : X0 + 36 + (i / (n - 1)) * (X1 - X0 - 72));
  const users = runs.map((r) => r.users ?? 0);
  const target = Math.max(0, ...runs.map((r) => r.target_users ?? 0));
  // Runde Achsenwerte (0, 2.000, 4.000 …) statt krummer Bruchteile; 3 bis 5 Schritte, je nachdem, was am wenigsten Luft lässt
  const peak = Math.max(...users, target, 1) * 1.1;
  const [step, count] = [3, 4, 5].map((k) => [niceStep(peak / k), k]).sort((a, b) => a[0] * a[1] - b[0] * b[1])[0];
  const maxU = step * count;
  const yU = (v: number) => Y1 - (v / maxU) * (Y1 - Y0);
  const ticks = Array.from({ length: count + 1 }, (_, i) => i * step);
  // Datum unter jedem Punkt; liegen mehrere Läufe am selben Tag, steht die Uhrzeit dabei
  const when = runs.map((r) => runLabel(r.name).split(", "));
  const sameDay = new Set(when.map((w) => w[0])).size < when.length;
  const alone = runs.map((r) => r.alone ?? null);
  const path = users.map((u, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${yU(u).toFixed(1)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Verlauf der Kapazität in ${g.unit} über ${n} Läufe`} className="h-auto w-full">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={X0} x2={X1} y1={yU(t)} y2={yU(t)} stroke="#fff" strokeOpacity="0.08" />
          <text
            x={X0 - 6}
            y={yU(t) + 4}
            textAnchor="end"
            fontSize="10"
            fill="#fff"
            fillOpacity="0.55"
            fontFamily="JetBrains Mono, monospace"
          >
            {nf(t, Number.isInteger(t) ? 0 : 1)}
          </text>
        </g>
      ))}
      {target > 0 && (
        <>
          <line x1={X0} x2={X1} y1={yU(target)} y2={yU(target)} stroke="#fff" strokeOpacity="0.5" strokeDasharray="4 6" />
          <text
            x={X1}
            y={yU(target) - 5}
            textAnchor="end"
            fontSize="10"
            fill="#fff"
            fillOpacity="0.7"
            fontFamily="JetBrains Mono, monospace"
          >
            Bedarf {nf(target, 0)}
          </text>
        </>
      )}
      <path d={path} fill="none" stroke="#22D3EE" strokeWidth="2.5" strokeLinejoin="round" />
      {runs.map((r, i) => (
        <g key={r.name}>
          <circle cx={x(i)} cy={yU(users[i])} r={r.pinned ? 7 : 5} fill={DOT[r.status ?? ""] ?? "#94A3B8"} stroke="#0a0b14" strokeWidth="2">
            <title>
              {`${r.title ?? runLabel(r.name)}: ${nf(users[i], 0)} ${g.unit}${alone[i] != null ? `, ${g.wait} ohne Andrang ${secs(alone[i])}` : ""}`}
            </title>
          </circle>
          <text x={x(i)} y={H - 18} textAnchor="middle" fontSize="10" fill="#fff" fillOpacity="0.6" fontFamily="JetBrains Mono, monospace">
            {when[i][0].slice(0, 6)}
            {sameDay && when[i][1] ? ` ${when[i][1]}` : ""}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Verlauf über die Zeit: Kapazität aller Läufe gleicher Art und Adresse; die Zeit ohne Andrang steht im Satz darunter. */
export function Trend({ runs }: { runs: RunInfo[] }) {
  const id = useId();
  const groups = trendGroups(runs).filter((g) => g.runs.length >= 2);
  const [key, setKey] = useState<string>(groups[0]?.key ?? "");
  const g = groups.find((x) => x.key === key) ?? groups[0];
  if (!g) return null;

  return (
    <section aria-labelledby={`${id}-h`} className="card mt-6 p-5 sm:p-7">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id={`${id}-h`} className="font-display text-xl font-bold">
          Verlauf
        </h2>
        {groups.length > 1 ? (
          <>
            <label htmlFor={`${id}-g`} className="sr-only">
              Ziel wählen
            </label>
            <Select
              id={`${id}-g`}
              label="Ziel"
              value={g.key}
              options={groups.map((x) => ({ value: x.key, label: `${x.label} (${x.runs.length})` }))}
              onChange={setKey}
            />
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
