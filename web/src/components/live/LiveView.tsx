"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AppHeader, StatusPill, TargetChip, type PillTone } from "@/components/AppHeader";
import { Meter } from "@/components/Meter";
import { Sparkline } from "@/components/Sparkline";
import {
  curvePoints,
  liveFocus,
  liveHeadline,
  phaseSteps,
  progress,
  sloSeconds,
  stageTimer,
  terms,
  type PhaseStep,
  type Status,
} from "@/lib/derive";
import { parseLogLine, type LiveState } from "@/lib/events";
import { approxUsers, clock, hostLabel, nf, runLabel } from "@/lib/format";
import type { Sample, Summary } from "@/lib/types";
import { LoadCurve } from "./LoadCurve";
import { LoadRing } from "./LoadRing";

const TONE_TEXT: Record<Status, string> = {
  good: "text-mint",
  warn: "text-amber-soft",
  bad: "text-rose-soft",
  none: "text-cyan",
};

function StopButton({ onStop }: { onStop: () => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const keep = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) keep.current?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  return (
    <>
      <button ref={trigger} type="button" className="btn btn-danger" onClick={() => setOpen(true)}>
        <span aria-hidden="true" className="size-[9px] rounded-sm bg-rose-soft" />
        Abbrechen
      </button>
      {open && (
        <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4" onClick={close}>
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="stop-titel"
            aria-describedby="stop-text"
            className="card w-full max-w-md bg-ink-2 p-6"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") close();
              // Fokus bleibt im Dialog: es gibt genau zwei Schaltflächen
              if (e.key === "Tab") {
                e.preventDefault();
                const buttons = e.currentTarget.querySelectorAll("button");
                (document.activeElement === buttons[0] ? buttons[1] : buttons[0]).focus();
              }
            }}
          >
            <h2 id="stop-titel" className="font-display text-xl font-bold">
              Test wirklich abbrechen?
            </h2>
            <p id="stop-text" className="mt-2 text-sm text-white/75">
              Der Bericht wird mit den bisherigen Messwerten erstellt. Fortsetzen lässt sich der Test nicht.
            </p>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <button ref={keep} type="button" className="btn btn-ghost" onClick={close}>
                Weiterlaufen lassen
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => {
                  setOpen(false);
                  onStop();
                }}
              >
                Ja, abbrechen
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function StepIcon({ status }: { status: PhaseStep["status"] }) {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" className="relative shrink-0">
      {status === "done" && (
        <>
          <circle cx="14" cy="14" r="13" fill="#34D399" fillOpacity="0.14" stroke="#34D399" strokeOpacity="0.5" />
          <path d="M9 14.2l3.4 3.4L19 11" fill="none" stroke="#34D399" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {status === "active" && (
        <>
          <circle cx="14" cy="14" r="12.5" fill="#7C5CFF" fillOpacity="0.22" stroke="#22D3EE" strokeWidth="2" />
          <circle cx="14" cy="14" r="5" fill="#fff" />
        </>
      )}
      {status === "pending" && <circle cx="14" cy="14" r="13" fill="none" stroke="#fff" strokeOpacity="0.25" />}
    </svg>
  );
}

const STATUS_WORD = { done: "erledigt", active: "läuft gerade", pending: "kommt noch" };

function Timeline({ steps }: { steps: PhaseStep[] }) {
  return (
    <ol aria-label="Ablauf des Tests" className="mt-6 flex flex-col">
      {steps.map((s, i) => (
        <li
          key={s.key}
          aria-current={s.status === "active" ? "step" : undefined}
          className={`relative flex gap-3 px-3 py-3 ${
            s.status === "active"
              ? "rounded-[14px] border border-[#9980ff]/30 bg-gradient-to-r from-violet/20 to-violet/[0.03]"
              : "border border-transparent"
          }`}
        >
          {i < steps.length - 1 && (
            <span
              aria-hidden="true"
              className={`absolute bottom-[-14px] left-[25px] top-[42px] w-0.5 ${s.status === "done" ? "bg-mint/50" : "bg-white/10"}`}
            />
          )}
          <StepIcon status={s.status} />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className={`text-sm ${s.status === "pending" ? "font-medium text-white/65" : "font-semibold text-white"}`}>
                {s.title}
              </span>
              {s.duration != null && s.duration > 0 && (
                <span className={`font-mono text-[11px] ${s.status === "active" ? "font-bold text-cyan" : "text-white/60"}`}>
                  <span className="sr-only">Dauer </span>
                  {clock(s.duration)}
                </span>
              )}
            </div>
            <p className={`mt-0.5 text-xs ${s.status === "active" ? "font-medium text-cyan-soft" : "text-white/60"}`}>{s.detail}</p>
            <span className="sr-only">{STATUS_WORD[s.status]}</span>
            {s.status === "active" && s.fraction != null && (
              <Meter value={s.fraction} label={`Fortschritt ${s.title}`} className="mt-2.5 h-[3px]" decorative />
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Forecast({ summary }: { summary: Summary }) {
  const users = approxUsers(summary.capacity.users);
  const q = summary.quality?.overall;
  const level = q === "hoch" ? 3 : q === "mittel" ? 2 : q === "niedrig" ? 1 : summary.capacity.source === "rate" ? 2 : users ? 1 : 0;
  const word = ["noch offen", "vorläufig", "mittel", "hoch"][level];
  return (
    <section
      aria-labelledby="prognose-titel"
      className="rounded-[20px] border border-[#a68cff]/60 bg-gradient-to-br from-violet/30 to-cyan/10 p-6 shadow-[0_20px_60px_rgb(124_92_255/0.35)] backdrop-blur-[30px]"
    >
      <h2 id="prognose-titel" className="eyebrow text-[#ccbfff]">
        Prognose
      </h2>
      <p className="mt-3 text-sm font-medium text-white/75">Reicht für etwa</p>
      <p className="bg-gradient-to-r from-white to-[#99ebff] bg-clip-text font-display text-[68px] font-bold leading-[1.1] tracking-[-0.04em] text-transparent [filter:drop-shadow(0_0_28px_rgb(124_92_255/0.7))]">
        {users != null ? nf(users, 0) : "–"}
      </p>
      <p className="text-sm font-medium text-white/75">{terms(summary.config).peopleLong}</p>
      <p className="mt-4 border-t border-white/10 pt-3.5 text-xs leading-[18px] text-white/70">
        {summary.config.kind === "api"
          ? "Bei zufällig verteilten Anfragen, so wie im Alltag."
          : summary.config.kind === "web"
            ? `Wenn jeder Besucher etwa alle ${nf(summary.capacity.think_time, 0)} Sekunden eine Seite aufruft.`
            : `Wenn jede Person etwa alle ${nf(summary.capacity.think_time, 0)} Sekunden fragt.`}{" "}
        Wird genauer, je länger der Test läuft.
      </p>
      <p className="mt-2 font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-[#ccbfff]">
        Sicherheit{" "}
        <span aria-hidden="true" className="mx-1 tracking-normal">
          {"●".repeat(level)}
          {"○".repeat(3 - level)}
        </span>{" "}
        <span className="normal-case">{word}</span>
      </p>
    </section>
  );
}

function ServerCard({ samples }: { samples: Sample[] }) {
  const withMetrics = samples.filter((s) => s.kv != null || s.waiting != null);
  const last = withMetrics[withMetrics.length - 1];
  return (
    <section aria-labelledby="server-titel" className="card p-6">
      <div className="flex items-baseline justify-between">
        <h2 id="server-titel" className="eyebrow font-medium text-white/65">
          Server
        </h2>
        <span className="font-mono text-[11px] text-white/55">/metrics</span>
      </div>
      {!last ? (
        <p className="mt-4 text-xs leading-[18px] text-white/65">
          Der Server liefert keine eigenen Messwerte. Der Test läuft trotzdem – nur ohne Blick ins Innere.
        </p>
      ) : (
        <>
          {last.kv != null && (
            <>
              <p className="mt-4 flex justify-between text-xs font-medium text-white/70">
                Gedächtnis für Gespräche
                <span className={`font-mono font-bold ${last.kv > 90 ? "text-rose-soft" : last.kv > 65 ? "text-amber" : "text-mint"}`}>
                  {nf(last.kv, 0)} %
                </span>
              </p>
              <Meter value={last.kv / 100} label="Gedächtnis für Gespräche" gradient="amber" className="mt-2 h-1.5" decorative />
            </>
          )}
          <p className="mt-4 flex justify-between text-xs font-medium text-white/70">
            Warten in der Schlange
            <span className="font-mono font-bold text-white">{nf(last.waiting ?? 0, 0)}</span>
          </p>
          <Sparkline values={withMetrics.slice(-90).map((s) => s.waiting ?? 0)} color="#FBBF24" className="mt-2 h-14 w-full" />
        </>
      )}
    </section>
  );
}

const LOG_STYLE = {
  heading: "font-bold text-lilac",
  stage: "text-cyan",
  good: "text-mint",
  bad: "text-rose-soft",
  plain: "text-white/75",
};

function LogPanel({ lines, live }: { lines: string[]; live: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const shown = lines.slice(-80);
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines.length]);
  return (
    <section
      aria-labelledby="protokoll-titel"
      className="overflow-hidden rounded-[20px] border border-white/[0.08] bg-[#030408]/80 shadow-[0_24px_48px_rgb(0_0_0/0.35)]"
    >
      <div className="flex items-center gap-4 border-b border-white/[0.06] px-5 py-3.5">
        <span aria-hidden="true" className="flex gap-1.5">
          <span className="size-2 rounded-full bg-rose/70" />
          <span className="size-2 rounded-full bg-amber/70" />
          <span className="size-2 rounded-full bg-mint/70" />
        </span>
        <h2 id="protokoll-titel" className="font-mono text-[11px] font-medium text-white/65">
          protokoll.log
        </h2>
        {live && <span className="ml-auto font-mono text-[11px] font-bold text-mint">● live</span>}
      </div>
      {/* aria-live aus: sonst liest der Screenreader jede Sekunde vor. Wichtiges steht in Überschrift und Statuspille. */}
      <div
        ref={box}
        role="log"
        aria-label="Protokoll"
        aria-live="off"
        tabIndex={0}
        className="h-[280px] overflow-y-auto px-5 py-3 font-mono text-[11px] leading-[22px]"
      >
        {shown.length === 0 && <p className="text-white/60">Noch keine Einträge.</p>}
        {shown.map((raw, i) => {
          const l = parseLogLine(raw);
          return (
            <p key={`${lines.length - shown.length + i}`} className="whitespace-pre-wrap break-words">
              <span className="text-white/55">{l.time}</span> <span className={LOG_STYLE[l.kind]}>{l.text}</span>
            </p>
          );
        })}
        {live && (
          <span aria-hidden="true" className="animate-blink text-cyan">
            ▍
          </span>
        )}
      </div>
    </section>
  );
}

function pill(live: LiveState, elapsed: number): { tone: PillTone; tag: string; text: string } {
  switch (live.state) {
    case "running":
      return { tone: "live", tag: "Live", text: `Test läuft · ${clock(elapsed)}` };
    case "done":
      return { tone: "done", tag: "Fertig", text: `Abgeschlossen in ${clock(elapsed)} min` };
    case "stopped":
      return { tone: "warn", tag: "Gestoppt", text: "Test abgebrochen" };
    case "error":
      return { tone: "bad", tag: "Fehler", text: "Test fehlgeschlagen" };
    default:
      return { tone: "idle", tag: "Bereit", text: live.connected ? "Kein Test aktiv" : "Verbinde …" };
  }
}

export function LiveView({ live, onStop }: { live: LiveState; onStop: () => void }) {
  const { summary, samples } = live;
  const running = live.state === "running";
  const elapsed = samples[samples.length - 1]?.t ?? 0;
  const p = pill(live, elapsed);
  const crumbs = [
    { label: "Läufe", href: "/laeufe" },
    ...(summary ? [{ label: `${hostLabel(summary.config.base_url)}${summary.config.model ? ` · ${summary.config.model}` : ""}` }] : []),
    { label: live.run ? `Lauf ${runLabel(live.run)}` : "Aktueller Lauf" },
  ];
  const finished = live.state === "done" || live.state === "stopped" || live.state === "error";
  const resultHref = `/laeufe/${live.run}`;

  const header = (
    <AppHeader
      crumbs={crumbs}
      status={<StatusPill {...p} />}
      actions={
        <>
          {summary && <TargetChip host={hostLabel(summary.config.base_url)} model={summary.config.model} />}
          {running && <StopButton onStop={onStop} />}
          {!running && (
            <Link href="/" className="btn btn-primary">
              <span aria-hidden="true">+</span> Neuer Test
            </Link>
          )}
        </>
      }
    />
  );

  if (!summary) {
    return (
      <>
        {header}
        <main id="inhalt" className="mx-auto max-w-[1440px] px-4 py-16 sm:px-8">
          <div className="card mx-auto max-w-xl p-8 text-center">
            <h1 className="font-display text-[34px] font-bold tracking-[-0.02em]">
              {live.connected ? "Gerade läuft kein Test." : "Verbinde mit dem Test …"}
            </h1>
            {live.error && (
              <p role="alert" className="mt-4 rounded-xl border border-rose/45 bg-rose/10 px-4 py-3 text-sm text-rose-soft">
                {live.error}
              </p>
            )}
            {live.connected && (
              <p className="mt-6">
                <Link href="/" className="btn btn-primary">
                  Neuen Test starten
                </Link>
              </p>
            )}
          </div>
        </main>
      </>
    );
  }

  const steps = phaseSteps(summary, samples, running);
  const prog = progress(summary, samples);
  const focus = liveFocus(summary, samples);
  const measured = liveHeadline(summary);
  // Ohne Messwerte und ohne laufenden Test gibt es nichts mehr abzuwarten.
  const head =
    !running && measured.tone === "none"
      ? { ...measured, title: "Der Test wurde beendet.", text: "Es wurden noch keine Messwerte aufgenommen." }
      : measured;
  const timer = running ? stageTimer(summary, samples) : null;
  const activeIndex = steps.findIndex((s) => s.status === "active");
  const levels = summary.config.levels.split(",").map(Number).filter(Boolean);
  const web = summary.config.kind === "web" || summary.config.kind === "api";
  const t = terms(summary.config);
  const slo = sloSeconds(summary.config);
  const profileName = Number(summary.config.soak_minutes) <= 5 ? "Schnell" : "Gründlich";

  return (
    <>
      {header}
      <main id="inhalt" className="mx-auto grid max-w-[1440px] gap-6 px-4 py-8 sm:px-8 xl:grid-cols-[300px_minmax(0,1fr)_300px]">
        {live.offline && (
          <p
            role="status"
            aria-label="Verbindung"
            className="rounded-xl border border-amber/35 bg-amber/10 px-4 py-3 text-sm text-amber-soft xl:col-span-3"
          >
            Verbindung unterbrochen – wird neu aufgebaut. Der Test selbst läuft weiter; die Anzeige zeigt den letzten
            bekannten Stand.
          </p>
        )}
        {(live.error || finished) && (
          <div className="xl:col-span-3">
            {live.error && (
              <p role="alert" className="mb-3 rounded-xl border border-rose/45 bg-rose/10 px-4 py-3 text-sm text-rose-soft">
                {live.error}
              </p>
            )}
            {finished && live.run && (
              <p className="card flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                {live.state === "done"
                  ? "Der Test ist fertig."
                  : "Der Test wurde beendet – es gibt ein Ergebnis mit den bisherigen Messwerten."}
                <Link href={resultHref} className="btn btn-primary">
                  Ergebnis ansehen <span aria-hidden="true">→</span>
                </Link>
              </p>
            )}
          </div>
        )}

        <section aria-labelledby="ablauf-titel" className="card self-start p-3 pt-6 xl:row-span-2">
          <div className="px-3">
            <h2 id="ablauf-titel" className="eyebrow font-medium text-white/65">
              Ablauf
            </h2>
            <p className="mt-1.5 font-display text-xl font-bold">{profileName}</p>
            <p className="mt-3 text-xs font-medium text-white/70">
              {running
                ? `${prog.pct} % geschafft · noch ≈ ${Math.max(1, Math.round(prog.remaining / 60))} min`
                : `Dauer ${clock(elapsed)} min`}
            </p>
            <Meter value={running ? prog.pct / 100 : 1} label="Gesamtfortschritt" gradient="overall" className="mt-2.5 h-1.5" />
          </div>
          <Timeline steps={steps} />
        </section>

        <div className="flex min-w-0 flex-col gap-6">
          <section aria-labelledby="live-titel" className="card p-7">
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-white/65">
              {activeIndex >= 0
                ? `Schritt ${activeIndex + 1} von ${steps.length} · ${steps[activeIndex].title}`
                : "Alle Schritte abgeschlossen"}
            </p>
            <div className="mt-4 grid items-center gap-8 md:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
              <LoadRing focus={focus} />
              <div className="min-w-0">
                <div aria-live="polite">
                  <h1 id="live-titel" className="font-display text-[34px] font-bold leading-tight tracking-[-0.02em]">
                    {head.title}
                  </h1>
                  <p className="mt-2 max-w-sm text-sm leading-[21px] text-white/70">{head.text}</p>
                </div>
                {head.kpis.length > 0 && (
                  <dl className="mt-4 grid grid-cols-2 gap-3">
                    {head.kpis.map((k) => (
                      <div key={k.label} className="tile px-3.5 py-3">
                        <dt className="text-[11px] font-medium text-white/65">{k.label}</dt>
                        <dd className="mt-1.5">
                          <span className="font-display text-[28px] font-bold leading-none tracking-[-0.02em]">{k.value}</span>{" "}
                          <span className="font-display text-[15px] font-bold text-white/60">{k.unit}</span>
                          <span className={`mt-1.5 block text-[11px] font-medium ${TONE_TEXT[k.tone]}`}>{k.note}</span>
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                {timer && (
                  <div className="mt-4 flex items-center gap-4">
                    <p className="shrink-0 font-mono text-[11px] text-white/65">Stufe endet in {clock(timer.remaining)}</p>
                    <Meter value={timer.fraction} label="Fortschritt der Stufe" className="h-1" decorative />
                  </div>
                )}
              </div>
            </div>
          </section>

          <section aria-labelledby="kurve-h" className="card p-7">
            <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
              <h2 id="kurve-h" className="font-display text-xl font-bold tracking-[-0.01em]">
                {summary.config.kind === "api"
                  ? "Wie viel schafft sie, wenn mehr Anfragen kommen?"
                  : web
                    ? "Wie viel schafft sie, wenn mehr Besucher kommen?"
                    : "Wie viel schafft er, wenn mehr Leute kommen?"}
              </h2>
              <p className="flex gap-5 text-xs font-medium text-white/70">
                <span>
                  <span aria-hidden="true" className="text-[#9980ff]">
                    ●
                  </span>{" "}
                  {t.throughput}
                </span>
                <span>
                  <span aria-hidden="true" className="text-pink">
                    ●
                  </span>{" "}
                  {t.wait}
                </span>
              </p>
            </div>
            <p className="mb-4 mt-1 text-[13px] text-white/65">
              Jeder Punkt ist eine Stufe. Gemessen wird erst, wenn sich die Last eingeschwungen hat.
            </p>
            <LoadCurve
              points={curvePoints(summary)}
              levels={levels}
              sloTtft={slo}
              live={running}
              labels={{ throughput: t.throughput, unit: t.throughputUnit, wait: t.wait, goal: t.goal(slo) }}
            />
          </section>
        </div>

        <div className="flex min-w-0 flex-col gap-6">
          <Forecast summary={summary} />
          {/* Eine Website liefert keine Innenwerte wie ein KI-Server (/metrics) */}
          {!web && <ServerCard samples={samples} />}
          <LogPanel lines={live.logs} live={running} />
        </div>
      </main>
    </>
  );
}
