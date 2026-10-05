import { useId } from "react";

/** Kleine Verlaufskurve ohne Achsen (rein dekorativ – die Zahl steht daneben). */
export function Sparkline({ values, color, className = "h-14 w-full" }: { values: number[]; color: string; className?: string }) {
  const id = useId();
  if (values.length < 2) return <div className={className} aria-hidden="true" />;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * 100, 38 - (v / max) * 34] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop stopColor={color} stopOpacity="0.35" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L100 40 L0 40 Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <circle cx={lx} cy={ly} r="1.6" fill={color} />
    </svg>
  );
}
