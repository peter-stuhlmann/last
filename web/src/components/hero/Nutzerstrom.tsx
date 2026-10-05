"use client";

import { useEffect, useRef } from "react";
import { DOTS, LINES } from "./nutzerstrom-data";

/**
 * Die Illustration der Startseite: simulierte Personen schicken Anfragen zum Server.
 *
 * Animiert mit SVG-eigenen Animationen (SMIL) statt mit einer Bibliothek:
 * kein zusätzliches JavaScript im Bundle und keine style-Attribute (strenge CSP).
 * Alle Zeiten leiten sich aus dem Index ab – so ist das HTML vom Server und im Browser gleich.
 */
export function Nutzerstrom({ className = "h-auto w-full" }: { className?: string }) {
  const ref = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = ref.current;
    if (!svg || typeof svg.pauseAnimations !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    let visible = true;
    // Läuft nur, wenn es jemand sieht und Bewegung nicht abgestellt ist
    const apply = () => (media.matches || !visible ? svg.pauseAnimations() : svg.unpauseAnimations());
    if (media.matches) svg.pauseAnimations();

    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      apply();
    });
    observer.observe(svg);
    media.addEventListener("change", apply);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", apply);
    };
  }, []);

  return (
    <svg ref={ref} viewBox="0 0 600 600" fill="none" aria-hidden="true" className={className}>
      <defs>
        <radialGradient id="strom-hof" cx="300" cy="300" r="300" gradientUnits="userSpaceOnUse">
          <stop stopColor="#22D3EE" stopOpacity="0.22" />
          <stop offset="1" stopColor="#22D3EE" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="strom-kern" cx="300" cy="300" r="96" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" />
          <stop offset="0.25" stopColor="#C4B5FD" />
          <stop offset="0.6" stopColor="#7C5CFF" stopOpacity="0.5" />
          <stop offset="1" stopColor="#7C5CFF" stopOpacity="0" />
        </radialGradient>
      </defs>

      <circle cx="300" cy="300" r="300" fill="url(#strom-hof)" />

      {/* Gestrichelte Bahnen drehen sich langsam gegeneinander */}
      <circle cx="300" cy="300" r="270" stroke="#fff" strokeOpacity="0.06" strokeDasharray="2 8">
        <animateTransform attributeName="transform" type="rotate" from="0 300 300" to="360 300 300" dur="180s" repeatCount="indefinite" />
      </circle>
      <circle cx="300" cy="300" r="210" stroke="#fff" strokeOpacity="0.09" strokeDasharray="1 6">
        <animateTransform attributeName="transform" type="rotate" from="360 300 300" to="0 300 300" dur="120s" repeatCount="indefinite" />
      </circle>
      <circle cx="300" cy="300" r="150" stroke="#fff" strokeOpacity="0.12" />
      <circle cx="300" cy="300" r="96" stroke="#fff" strokeOpacity="0.18" />

      {/* Welle, die sich vom Server ausbreitet: „Antwort ist raus“ */}
      <circle cx="300" cy="300" r="62" stroke="#A5B4FC" strokeWidth="1.5" opacity="0">
        <animate attributeName="r" values="62;150" dur="3.2s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.5;0" dur="3.2s" repeatCount="indefinite" />
      </circle>

      {LINES.map(([x1, y1, x2, y2, color, opacity], i) => {
        const dur = `${(1.5 + (i % 5) * 0.4).toFixed(1)}s`;
        const begin = `${((i * 0.83) % 4).toFixed(2)}s`;
        // Paket fliegt, danach kurze Pause bis zur nächsten Anfrage
        const timing = { dur, begin, repeatCount: "indefinite", calcMode: "spline", keySplines: "0.4 0 0.6 1" } as const;
        return (
          <g key={`${x1}-${y1}`}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeOpacity={opacity} strokeWidth="1.5" strokeLinecap="round">
              <animate
                attributeName="stroke-opacity"
                values={`${opacity};${Math.min(1, opacity + 0.35).toFixed(2)};${opacity}`}
                dur={dur}
                begin={begin}
                repeatCount="indefinite"
              />
            </line>
            <circle data-paket="" cx={x1} cy={y1} r="2.6" fill="#fff" opacity="0">
              <animate attributeName="cx" values={`${x1};${x2}`} keyTimes="0;1" {...timing} />
              <animate attributeName="cy" values={`${y1};${y2}`} keyTimes="0;1" {...timing} />
              <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.15;0.8;1" dur={dur} begin={begin} repeatCount="indefinite" />
            </circle>
          </g>
        );
      })}

      {DOTS.map(([cx, cy, r, color, opacity], i) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={r} fill={color} fillOpacity={opacity}>
          {/* Jeder dritte Punkt funkelt – genug Leben, ohne unruhig zu werden */}
          {i % 3 === 0 && (
            <animate
              attributeName="fill-opacity"
              values={`${opacity};${(opacity * 0.25).toFixed(2)};${opacity}`}
              dur={`${3 + (i % 7) * 0.6}s`}
              begin={`${((i * 0.37) % 5).toFixed(2)}s`}
              repeatCount="indefinite"
            />
          )}
        </circle>
      ))}

      {/* Server in der Mitte: der Kern „atmet“ */}
      <circle cx="300" cy="300" r="96" fill="url(#strom-kern)" fillOpacity="0.55">
        <animate attributeName="fill-opacity" values="0.55;0.85;0.55" dur="3.2s" repeatCount="indefinite" />
      </circle>
      <circle cx="300" cy="300" r="54" fill="#0B0D14" stroke="#A5B4FC" strokeOpacity="0.6" strokeWidth="1.5" />
      <circle cx="300" cy="300" r="62" stroke="#22D3EE" strokeOpacity="0.35" strokeDasharray="3 5">
        <animateTransform attributeName="transform" type="rotate" from="0 300 300" to="360 300 300" dur="24s" repeatCount="indefinite" />
      </circle>
      {[
        { y: 280, led: "#34D399", dur: "1.1s" },
        { y: 296, led: "#22D3EE", dur: "0.7s" },
        { y: 312, led: "#A5B4FC", dur: "1.6s" },
      ].map((row) => (
        <g key={row.y}>
          <rect x="278" y={row.y} width="44" height="12" rx="3" stroke="#E0E7FF" strokeWidth="1.6" />
          <circle cx="314" cy={row.y + 6} r="1.8" fill={row.led}>
            <animate attributeName="opacity" values="1;0.25;1" dur={row.dur} repeatCount="indefinite" />
          </circle>
        </g>
      ))}
    </svg>
  );
}
