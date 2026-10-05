import Link from "next/link";
import type { ReactNode } from "react";

export function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="logo-g" x1="7" y1="24" x2="23" y2="6" gradientUnits="userSpaceOnUse">
          <stop stopColor="#7C5CFF" />
          <stop offset="1" stopColor="#22D3EE" />
        </linearGradient>
      </defs>
      <rect width="30" height="30" rx="9" fill="#11131C" />
      <rect x="0.5" y="0.5" width="29" height="29" rx="8.5" stroke="#fff" strokeOpacity="0.1" />
      <rect x="7" y="17" width="4" height="7" rx="2" fill="url(#logo-g)" opacity="0.55" />
      <rect x="13" y="12" width="4" height="12" rx="2" fill="url(#logo-g)" opacity="0.8" />
      <rect x="19" y="6" width="4" height="18" rx="2" fill="url(#logo-g)" />
    </svg>
  );
}

export type PillTone = "idle" | "live" | "done" | "warn" | "bad";

const PILL: Record<PillTone, { box: string; dot: string; tag: string; text: string }> = {
  idle: { box: "border-white/10 bg-white/[0.04]", dot: "bg-mint", tag: "text-white/70", text: "text-white/80" },
  live: {
    box: "border-mint/35 bg-mint/10 shadow-[0_0_24px_rgb(52_211_153/0.25)]",
    dot: "bg-mint animate-pulse-dot",
    tag: "text-mint",
    text: "text-[#D9FAEB]",
  },
  done: { box: "border-mint/35 bg-mint/10 shadow-[0_0_24px_rgb(52_211_153/0.25)]", dot: "bg-mint", tag: "text-mint", text: "text-[#D9FAEB]" },
  warn: { box: "border-amber/35 bg-amber/10", dot: "bg-amber", tag: "text-amber-soft", text: "text-white/85" },
  bad: { box: "border-rose/45 bg-rose/10", dot: "bg-rose", tag: "text-rose-soft", text: "text-white/85" },
};

/** Die Statuspille in der Kopfzeile. Änderungen werden Screenreadern angesagt. */
export function StatusPill({ tone, tag, text }: { tone: PillTone; tag: string; text: string }) {
  const c = PILL[tone];
  return (
    <p role="status" className={`flex h-8 items-center gap-2.5 rounded-full border pl-3.5 pr-4 ${c.box}`}>
      <span aria-hidden="true" className={`size-2 rounded-full shadow-[0_0_8px_2px_currentColor] ${c.dot}`} />
      <span className={`font-mono text-xs font-bold uppercase tracking-[0.14em] ${c.tag}`}>{tag}</span>
      <span className={`text-[13px] font-medium ${c.text}`}>{text}</span>
    </p>
  );
}

export interface Crumb {
  label: string;
  href?: string;
}

export function AppHeader({ crumbs, status, actions }: { crumbs: Crumb[]; status?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="border-b border-white/[0.06]">
      <div className="mx-auto flex min-h-[72px] max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-8">
        <Link href="/" className="flex items-center gap-2.5" aria-label="LAST – Startseite">
          <Logo />
          <span className="font-display text-xl font-bold tracking-[0.12em]">LAST</span>
        </Link>
        <nav aria-label="Brotkrumen" className="min-w-0">
          <ol className="flex flex-wrap items-center gap-x-3 text-sm font-medium">
            {crumbs.map((c, i) => {
              const last = i === crumbs.length - 1;
              return (
                <li key={c.label} className="flex items-center gap-x-3">
                  {i > 0 && (
                    <span aria-hidden="true" className="text-white/40">
                      /
                    </span>
                  )}
                  {c.href && !last ? (
                    <Link href={c.href} className="text-white/65 hover:text-white">
                      {c.label}
                    </Link>
                  ) : (
                    <span aria-current={last ? "page" : undefined} className={last ? "text-white/90" : "text-white/65"}>
                      {c.label}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
        {status && <div className="lg:mx-auto">{status}</div>}
        {actions && <div className="ml-auto flex flex-wrap items-center gap-1.5">{actions}</div>}
      </div>
    </header>
  );
}

/** Kleine Anzeige „Adresse · Modell“ rechts in der Kopfzeile. */
export function TargetChip({ host, model }: { host: string; model?: string | null }) {
  return (
    <p className="flex h-9 items-center gap-2 rounded-[10px] border border-white/[0.08] bg-white/[0.04] px-3 font-mono text-xs font-medium text-white/75">
      <span aria-hidden="true" className="text-sm text-cyan">
        ◎
      </span>
      <span className="sr-only">Getesteter Server: </span>
      {host}
      {model ? ` · ${model}` : ""}
    </p>
  );
}
