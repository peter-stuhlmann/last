import { nf, secs } from "@/lib/format";
import { niceStep } from "@/lib/scale";

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
 * „Bleibt es schnell, wenn mehr Leute kommen?“ – eine einzige Kurve: so lange warten fast alle (95 %) je Stufe,
 * dazu die Ziellinie. Grüne Punkte liegen im Ziel, rote nicht. Zwei Achsen (Leistung und Wartezeit) waren für
 * Laien kaum zu lesen; die Leistung steht im Hinweis am letzten Punkt und in der Tabelle für Screenreader.
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
  labels: { throughput: string; unit: string; wait: string; goal: string; axis: string };
}) {
  const xs = [...new Set([...levels, ...points.map((p) => p.c)])].sort((a, b) => a - b);
  const x = (c: number) => (xs.length < 2 ? X0 : X0 + (xs.indexOf(c) / (xs.length - 1)) * (X1 - X0));
  const r = (n: number) => Number(n.toFixed(1));

  // Die Ziellinie liegt immer gut sichtbar im unteren Drittel bis zur Mitte; sehr langsame Stufen werden oben gekappt
  const top = 4 * niceStep(Math.max(sloTtft * 2, ...points.map((p) => (p.ttft ?? 0) * 1.1)) / 4);
  const y = (v: number) => r(Y1 - (Math.min(v, top) / top) * (Y1 - Y0));
  const pts = points.filter((p) => p.ttft != null).map((p) => ({ ...p, px: r(x(p.c)), py: y(p.ttft as number) }));
  const line = smooth(pts.map((p) => [p.px, p.py]));
  const last = pts[pts.length - 1];
  const ySlo = y(sloTtft);
  const digits = (v: number) => (v < 10 ? 1 : 0);
  const tipX = last ? Math.min(Math.max(last.px - 158, X0 + 4), X1 - 174) : 0;
  const tipY = last ? (last.py > 90 ? last.py - 72 : last.py + 18) : 0;

  return (
    <figure className="m-0">
      <svg viewBox="0 0 672 300" className="h-auto w-full" role="img" aria-labelledby="kurve-titel">
        <title id="kurve-titel">
          {points.length
            ? `Diagramm: ${labels.wait} bei ${points.map((p) => p.c).join(", ")} gleichzeitig. Zahlen in der Tabelle darunter.`
            : "Diagramm: noch keine Stufe fertig gemessen."}
        </title>
        <defs>
          <linearGradient id="kurve-flaeche" x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#7C5CFF" stopOpacity="0.45" />
            <stop offset="1" stopColor="#7C5CFF" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="kurve-linie" x1={X0} x2={X1} y1="0" y2="0" gradientUnits="userSpaceOnUse">
            <stop stopColor="#7C5CFF" />
            <stop offset="1" stopColor="#22D3EE" />
          </linearGradient>
          <linearGradient id="kurve-zone" x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#F43F5E" stopOpacity="0.16" />
            <stop offset="1" stopColor="#F43F5E" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        <g aria-hidden="true" fontFamily="var(--font-mono)" fontSize="10">
          {[0, 1, 2, 3, 4].map((i) => {
            const v = (top / 4) * i;
            const yy = y(v);
            return (
              <g key={i}>
                <line x1={X0} x2={X1} y1={yy} y2={yy} stroke="#fff" strokeOpacity="0.06" />
                <text x={X0 - 8} y={yy + 3} textAnchor="end" fill="#fff" fillOpacity="0.6">
                  {`${nf(v, digits(top))} s`}
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
          <line x1={X0} x2={X1} y1={ySlo} y2={ySlo} stroke="#F43F5E" strokeOpacity="0.7" strokeDasharray="5 4" strokeWidth="1.5" />
          <text x={X1 - 8} y={ySlo - 7} textAnchor="end" fontFamily="var(--font-sans)" fontSize="11" fontWeight="600" fill="#FDA4AF">
            {labels.goal}
          </text>
          <text x={X0 + 8} y={Y0 + 16} fontFamily="var(--font-sans)" fontSize="11" fill="#FDA4AF" fillOpacity="0.8">
            zu langsam
          </text>

          {pts.length > 1 && (
            <>
              <path d={`${line} L${last.px} ${Y1} L${pts[0].px} ${Y1} Z`} fill="url(#kurve-flaeche)" />
              <path d={line} fill="none" stroke="url(#kurve-linie)" strokeWidth="10" strokeOpacity="0.25" strokeLinecap="round" />
              <path d={line} fill="none" stroke="url(#kurve-linie)" strokeWidth="3" strokeLinecap="round" />
            </>
          )}
          {pts.map((p) => (
            <circle key={p.px} cx={p.px} cy={p.py} r="5" fill="#0B0D14" stroke={p.ok ? "#34D399" : "#F43F5E"} strokeWidth="2.5" />
          ))}

          {last && (
            <>
              <line x1={last.px} x2={last.px} y1={Y0} y2={Y1} stroke="#22D3EE" strokeOpacity="0.35" strokeDasharray="2 4" />
              <circle cx={last.px} cy={last.py} r="16" fill="#22D3EE" fillOpacity="0.15" />
              <circle cx={last.px} cy={last.py} r="5" fill="#fff" />
              <g transform={`translate(${r(tipX)} ${r(tipY)})`}>
                <rect width="170" height="56" rx="10" fill="#08090F" fillOpacity="0.92" stroke="#22D3EE" strokeOpacity="0.4" />
                <text x="12" y="19" fontSize="9" fontWeight="700" letterSpacing="0.9" fill="#22D3EE">
                  {`${live ? "JETZT" : "ZULETZT"} · ${last.c} GLEICHZEITIG`}
                </text>
                <text x="12" y="41" fontFamily="var(--font-display)" fontSize="14" fontWeight="700" fill="#fff">
                  {`${secs(last.ttft)}  ·  ${nf(last.tps, digits(last.tps))} ${labels.unit}`}
                </text>
              </g>
            </>
          )}
        </g>
      </svg>
      <figcaption className="mt-1 pl-11 text-[11px] font-medium text-white/60">{labels.axis} →</figcaption>

      <table className="sr-only">
        <caption>
          {labels.wait} und {labels.throughput} je Stufe
        </caption>
        <thead>
          <tr>
            <th scope="col">{labels.axis}</th>
            <th scope="col">{labels.wait}</th>
            <th scope="col">{labels.throughput}</th>
            <th scope="col">Ziele erreicht</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.c}>
              <th scope="row">{p.c}</th>
              <td>{secs(p.ttft)}</td>
              <td>
                {nf(p.tps, digits(p.tps))} {labels.unit}
              </td>
              <td>{p.ok ? "ja" : "nein"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
