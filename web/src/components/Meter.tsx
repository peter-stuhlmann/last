import { useId } from "react";

const GRADIENTS = {
  violet: ["#7C5CFF", "#22D3EE"],
  overall: ["#34D399", "#7C5CFF", "#22D3EE"],
  mint: ["#34D399", "#22D3EE"],
  amber: ["#34D399", "#FBBF24"],
  rose: ["#F472B6", "#F43F5E"],
} as const;

/**
 * Fortschrittsbalken als SVG. Bewusst ohne style-Attribut, damit die strenge
 * Content Security Policy (keine Inline-Styles) eingehalten wird.
 */
export function Meter({
  value,
  label,
  gradient = "violet",
  className = "h-1.5",
  decorative = false,
}: {
  /** 0–1 */
  value: number;
  label: string;
  gradient?: keyof typeof GRADIENTS;
  className?: string;
  /** true, wenn der Wert direkt daneben schon als Text steht */
  decorative?: boolean;
}) {
  const id = useId();
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  const stops = GRADIENTS[gradient];
  const a11y = decorative
    ? ({ "aria-hidden": true } as const)
    : ({ role: "progressbar", "aria-label": label, "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": pct } as const);
  return (
    <div {...a11y} className={`w-full overflow-hidden rounded-full bg-white/[0.08] ${className}`}>
      <svg viewBox="0 0 100 4" preserveAspectRatio="none" className="block size-full" aria-hidden="true">
        <defs>
          <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="0" x2={Math.max(pct, 1)} y1="0" y2="0">
            {stops.map((color, i) => (
              <stop key={color} offset={i / (stops.length - 1)} stopColor={color} />
            ))}
          </linearGradient>
        </defs>
        <rect width={pct} height="4" rx="2" fill={`url(#${id})`} />
      </svg>
    </div>
  );
}
