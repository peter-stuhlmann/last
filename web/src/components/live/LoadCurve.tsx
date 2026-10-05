import { nf, secs } from "@/lib/format";

export interface CurvePoint {
  c: number;
  tps: number;
  ttft: number | null;
  ok: boolean;
}

const X0 = 44;
const X1 = 628;
const Y0 = 14;
const Y1 = 254;

function niceStep(raw: number): number {
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-9)));
  return ([1, 2, 2.5, 3, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
}

/** Weiche Linie durch die Punkte (waagerechte Tangenten, kein Überschwingen). */
function smooth(points: [number, number][]): string {
  return points
    .map(([x, y], i) => {
      if (i === 0) return `M${x} ${y}`;
      const mx = (points[i - 1][0] + x) / 2;
      return `C${mx} ${points[i - 1][1]} ${mx} ${y} ${x} ${y}`;
    })
    .join(" ");
}

/**
 * „Wie viel schafft er, wenn mehr Leute kommen?“ – Gesamtleistung (links) und
 * Wartezeit (rechts) je Stufe. Dieselben Zahlen stehen darunter als Tabelle für Screenreader.
 */
export function LoadCurve({
  points,
  levels,
  sloTtft,
  live,
  labels,
}: {
  points: CurvePoint[];
  levels: number[];
  sloTtft: number;
  live: boolean;
  /** Begriffe je nach Art des Tests (KI-Server oder Website) */
  labels: { throughput: string; unit: string; wait: string; goal: string };
}) {
  const xs = [...new Set([...levels, ...points.map((p) => p.c)])].sort((a, b) => a - b);
  const x = (c: number) => (xs.length < 2 ? X0 : X0 + (xs.indexOf(c) / (xs.length - 1)) * (X1 - X0));
  const r = (n: number) => Number(n.toFixed(1));

  const tpsTop = points.length ? 3 * niceStep(Math.max(...points.map((p) => p.tps), 1) / 3) : 300;
  const ttftTop = Math.ceil(Math.max(sloTtft * 2.5, ...points.map((p) => (p.ttft ?? 0) * 1.15)));
  const yTps = (v: number) => r(Y1 - (v / tpsTop) * (Y1 - Y0));
  const yTtft = (v: number) => r(Y1 - (Math.min(v, ttftTop) / ttftTop) * (Y1 - Y0));

  const tpsPts = points.map((p) => [r(x(p.c)), yTps(p.tps)] as [number, number]);
  const ttftPts = points.filter((p) => p.ttft != null).map((p) => [r(x(p.c)), yTtft(p.ttft as number)] as [number, number]);
  const tpsLine = smooth(tpsPts);
  const last = points[points.length - 1];
  const lastPt = tpsPts[tpsPts.length - 1];
  const ySlo = yTtft(sloTtft);
  // Seiten pro Sekunde sind oft einstellig – dann mit einer Nachkommastelle
  const digits = tpsTop < 10 ? 1 : 0;
  const tipX = lastPt ? Math.min(Math.max(lastPt[0] - 158, X0 + 4), X1 - 174) : 0;
  const tipY = lastPt ? (lastPt[1] > 90 ? lastPt[1] - 72 : lastPt[1] + 18) : 0;

  return (
    <figure className="m-0">
      <svg viewBox="0 0 672 300" className="h-auto w-full" role="img" aria-labelledby="kurve-titel">
        <title id="kurve-titel">
          {points.length
            ? `Diagramm: ${labels.throughput} und ${labels.wait} bei ${points.map((p) => p.c).join(", ")} gleichzeitig. Zahlen in der Tabelle darunter.`
            : "Diagramm: noch keine Stufe fertig gemessen."}
        </title>
        <defs>
          <linearGradient id="kurve-flaeche" x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#7C5CFF" stopOpacity="0.55" />
            <stop offset="1" stopColor="#7C5CFF" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="kurve-linie" x1={X0} x2={X1} y1="0" y2="0" gradientUnits="userSpaceOnUse">
            <stop stopColor="#7C5CFF" />
            <stop offset="1" stopColor="#22D3EE" />
          </linearGradient>
          <linearGradient id="kurve-zone" x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#F43F5E" stopOpacity="0.14" />
            <stop offset="1" stopColor="#F43F5E" stopOpacity="0" />
          </linearGradient>
        </defs>

        <g aria-hidden="true" fontFamily="var(--font-mono)" fontSize="10">
          {[0, 1, 2, 3].map((i) => {
            const y = Y1 - (i / 3) * (Y1 - Y0);
            return (
              <g key={i}>
                <line x1={X0} x2={X1} y1={y} y2={y} stroke="#fff" strokeOpacity="0.06" />
                <text x={X0 - 8} y={y + 3} textAnchor="end" fill="#fff" fillOpacity="0.6">
                  {nf((tpsTop / 3) * i, digits)}
                </text>
              </g>
            );
          })}
          {xs.map((c) => {
            const done = points.some((p) => p.c === c);
            const current = last?.c === c && live;
            return (
              <g key={c}>
                <line x1={x(c)} x2={x(c)} y1={Y0} y2={Y1} stroke="#fff" strokeOpacity="0.035" />
                <text
                  x={x(c)}
                  y={Y1 + 22}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight={current ? 700 : 400}
                  fill={current ? "#22D3EE" : "#fff"}
                  fillOpacity={current ? 1 : done ? 0.65 : 0.4}
                >
                  {c}
                </text>
              </g>
            );
          })}

          {/* Über dieser Linie warten die Leute länger als gewünscht */}
          <rect x={X0} y={Y0} width={X1 - X0} height={Math.max(0, ySlo - Y0)} fill="url(#kurve-zone)" />
          <line x1={X0} x2={X1} y1={ySlo} y2={ySlo} stroke="#F43F5E" strokeOpacity="0.6" strokeDasharray="4 4" />
          <text x={X1 - 8} y={ySlo - 6} textAnchor="end" fontFamily="var(--font-sans)" fontSize="11" fontWeight="500" fill="#FDA4AF">
            {labels.goal}
          </text>
          <text x={X1 + 10} y={Y0 + 3} fill="#F9A8D4">{`${ttftTop} s`}</text>
          <text x={X1 + 10} y={ySlo + 3} fill="#FDA4AF" fontWeight="700">{secs(sloTtft)}</text>
          <text x={X1 + 10} y={Y1 + 3} fill="#F9A8D4">0 s</text>

          {tpsPts.length > 1 && (
            <>
              <path d={`${tpsLine} L${lastPt[0]} ${Y1} L${tpsPts[0][0]} ${Y1} Z`} fill="url(#kurve-flaeche)" />
              <path d={tpsLine} fill="none" stroke="url(#kurve-linie)" strokeWidth="10" strokeOpacity="0.25" strokeLinecap="round" />
              <path d={tpsLine} fill="none" stroke="url(#kurve-linie)" strokeWidth="3" strokeLinecap="round" />
            </>
          )}
          {ttftPts.length > 1 && <path d={smooth(ttftPts)} fill="none" stroke="#F472B6" strokeWidth="2" strokeLinecap="round" />}
          {ttftPts.map(([px, py]) => (
            <circle key={px} cx={px} cy={py} r="3" fill="#F472B6" />
          ))}
          {tpsPts.map(([px, py]) => (
            <circle key={px} cx={px} cy={py} r="4" fill="#0B0D14" stroke="#A5B4FC" strokeWidth="2" />
          ))}

          {last && lastPt && (
            <>
              <line x1={lastPt[0]} x2={lastPt[0]} y1={Y0} y2={Y1} stroke="#22D3EE" strokeOpacity="0.35" strokeDasharray="2 4" />
              <circle cx={lastPt[0]} cy={lastPt[1]} r="16" fill="#22D3EE" fillOpacity="0.15" />
              <circle cx={lastPt[0]} cy={lastPt[1]} r="9" fill="#22D3EE" fillOpacity="0.3" />
              <circle cx={lastPt[0]} cy={lastPt[1]} r="5" fill="#fff" />
              <g transform={`translate(${r(tipX)} ${r(tipY)})`}>
                <rect width="170" height="56" rx="10" fill="#08090F" fillOpacity="0.92" stroke="#22D3EE" strokeOpacity="0.4" />
                <text x="12" y="19" fontSize="9" fontWeight="700" letterSpacing="0.9" fill="#22D3EE">
                  {`${live ? "JETZT" : "ZULETZT"} · ${last.c} GLEICHZEITIG`}
                </text>
                <text x="12" y="41" fontFamily="var(--font-display)" fontSize="14" fontWeight="700" fill="#fff">
                  {`${nf(last.tps, digits)} ${labels.unit}  ·  ${secs(last.ttft)}`}
                </text>
              </g>
            </>
          )}
        </g>
      </svg>
      <figcaption className="mt-1 pl-11 text-[11px] font-medium text-white/60">Personen gleichzeitig →</figcaption>

      <table className="sr-only">
        <caption>
          {labels.throughput} und {labels.wait} je Stufe
        </caption>
        <thead>
          <tr>
            <th scope="col">Personen gleichzeitig</th>
            <th scope="col">{labels.throughput}</th>
            <th scope="col">{labels.wait}</th>
            <th scope="col">Ziele erreicht</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.c}>
              <th scope="row">{p.c}</th>
              <td>
                {nf(p.tps, digits)} {labels.unit}
              </td>
              <td>{secs(p.ttft)}</td>
              <td>{p.ok ? "ja" : "nein"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
