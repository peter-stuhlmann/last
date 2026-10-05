import type { Focus } from "@/lib/derive";

const C = 160; // Mittelpunkt
const R = 128; // Radius des Rings
const LEN = 2 * Math.PI * R;
const TICKS = Array.from({ length: 72 }, (_, i) => i);

function polar(radius: number, turn: number): [number, number] {
  const a = turn * 2 * Math.PI - Math.PI / 2;
  return [Number((C + radius * Math.cos(a)).toFixed(2)), Number((C + radius * Math.sin(a)).toFixed(2))];
}

/** Der große Ring aus dem Entwurf: zeigt, wie weit der aktuelle Schritt ist. */
export function LoadRing({ focus }: { focus: Focus }) {
  const f = Math.min(1, Math.max(0, focus.fraction));
  const [kx, ky] = polar(R, f);
  return (
    <div
      role="img"
      aria-label={`${focus.label}: ${focus.value} ${focus.unit}`}
      className="relative mx-auto aspect-square w-full max-w-[320px]"
    >
      <svg viewBox="0 0 320 320" className="size-full" aria-hidden="true">
        <defs>
          <radialGradient id="ring-glow">
            <stop stopColor="#7C5CFF" stopOpacity="0.32" />
            <stop offset="0.7" stopColor="#7C5CFF" stopOpacity="0.04" />
            <stop offset="1" stopColor="#7C5CFF" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="ring-arc" x1="288" y1="32" x2="32" y2="288" gradientUnits="userSpaceOnUse">
            <stop stopColor="#22D3EE" />
            <stop offset="0.55" stopColor="#7C5CFF" />
            <stop offset="1" stopColor="#F472B6" />
          </linearGradient>
        </defs>
        <circle cx={C} cy={C} r="112" fill="url(#ring-glow)" />
        <circle cx={C} cy={C} r="104" fill="none" stroke="#fff" strokeOpacity="0.06" strokeDasharray="2 6" />
        {TICKS.map((i) => {
          const major = i % 6 === 0;
          const [x1, y1] = polar(146, i / 72);
          const [x2, y2] = polar(major ? 156 : 151, i / 72);
          const lit = i / 72 <= f && f > 0;
          return (
            <line
              key={i}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={lit ? "#A5B4FC" : "#fff"}
              strokeOpacity={lit ? 0.55 : 0.14}
              strokeWidth={major ? 2 : 1.2}
              strokeLinecap="round"
            />
          );
        })}
        <circle cx={C} cy={C} r={R} fill="none" stroke="#fff" strokeOpacity="0.06" strokeWidth="14" />
        {f > 0 && (
          <g transform={`rotate(-90 ${C} ${C})`} fill="none" stroke="url(#ring-arc)" strokeLinecap="round">
            <circle cx={C} cy={C} r={R} strokeWidth="30" strokeOpacity="0.22" strokeDasharray={`${f * LEN} ${LEN}`} />
            <circle cx={C} cy={C} r={R} strokeWidth="14" strokeDasharray={`${f * LEN} ${LEN}`} />
          </g>
        )}
        {f > 0 && f < 1 && (
          <>
            <circle cx={kx} cy={ky} r="11" fill="#22D3EE" fillOpacity="0.25" />
            <circle cx={kx} cy={ky} r="5.5" fill="#fff" />
          </>
        )}
      </svg>
      <div aria-hidden="true" className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="font-mono text-[11px] font-bold uppercase tracking-[0.12em] text-cyan">{focus.label}</span>
        <span className="bg-gradient-to-b from-white to-[#bfb8ff] bg-clip-text font-display text-[84px] sm:text-[96px] font-bold leading-none tracking-[-0.04em] text-transparent [filter:drop-shadow(0_0_30px_rgb(124_92_255/0.6))]">
          {focus.value}
        </span>
        <span className="mt-3 text-sm font-medium text-white/70">{focus.unit}</span>
      </div>
    </div>
  );
}
