import Link from "next/link";
import { AppHeader, StatusPill } from "@/components/AppHeader";
import { Nutzerstrom } from "@/components/hero/Nutzerstrom";
import { NewTestForm } from "@/components/NewTestForm";
import { Sparkline } from "@/components/Sparkline";
import { getDefaults, getRuns, getState, getSummary } from "@/lib/backend";
import { capacityView, curvePoints, terms, verdictView } from "@/lib/derive";
import { clock, hostLabel, nf, runLabel, secs } from "@/lib/format";
import { FALLBACK_API, FALLBACK_DEFAULTS, FALLBACK_FLOW, FALLBACK_QUICK, FALLBACK_WEB } from "@/lib/profile";

export const dynamic = "force-dynamic";

const VERDICT_STYLE = { good: "text-mint-soft", warn: "text-amber-soft", bad: "text-rose-soft", none: "text-white/70" };

async function lastRun() {
  const run = (await getRuns())?.[0];
  if (!run) return null;
  const summary = await getSummary(run.name);
  return summary ? { run, summary } : null;
}

export default async function Home() {
  const [defaults, state, last] = await Promise.all([getDefaults(), getState(), lastRun()]);
  const running = state?.state === "running";
  const cap = last ? capacityView(last.summary) : null;
  const verdict = last ? verdictView(last.summary) : null;
  const lastKind = last?.summary.config.kind ?? "llm";
  const lastIsWeb = lastKind !== "llm";
  const best = (lastIsWeb ? last?.summary.baseline?.e2e_p50 : last?.summary.baseline?.ttft_p50) ?? null;
  const started = last?.summary.meta.started;
  const finished = last?.summary.meta.finished;
  const duration = started && finished ? (Date.parse(finished) - Date.parse(started)) / 1000 : null;

  return (
    <>
      <AppHeader
        crumbs={[{ label: "Läufe", href: "/laeufe" }, { label: "Neuer Test" }]}
        status={
          running ? (
            <StatusPill tone="live" tag="Live" text="Ein Test läuft" />
          ) : (
            <StatusPill tone="idle" tag="Bereit" text="Kein Test aktiv" />
          )
        }
        actions={
          <Link href="/laeufe" className="btn btn-ghost">
            Frühere Läufe
          </Link>
        }
      />
      <main
        id="inhalt"
        className="mx-auto grid max-w-[1440px] gap-x-12 gap-y-10 px-4 pb-16 pt-10 sm:px-8 lg:grid-cols-[minmax(0,600px)_minmax(0,1fr)] lg:px-24 lg:pt-[72px]"
      >
        <div>
          {!defaults && (
            <p role="alert" className="mb-6 rounded-xl border border-amber/35 bg-amber/10 px-4 py-3 text-sm text-amber-soft">
              Das Test-Backend antwortet nicht. Läuft der Container „backend“? Die Seite zeigt solange Standardwerte.
            </p>
          )}
          {running && (
            <p className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-mint/35 bg-mint/10 px-4 py-3 text-sm">
              Gerade läuft ein Test. Ein zweiter kann erst danach starten.
              <Link href="/lauf" className="btn btn-ghost">
                Zuschauen <span aria-hidden="true">→</span>
              </Link>
            </p>
          )}
          <p className="eyebrow text-[#bfadff]">Lasttest · KI-Server, APIs &amp; Websites</p>
          <h1 className="-ml-1 mt-3 font-display text-[44px] font-bold leading-[1.02] tracking-[-0.035em] sm:text-[72px]">
            Wie viel hält
            <br />
            euer Server <span className="bg-gradient-to-r from-[#a68cff] to-cyan bg-clip-text text-transparent">aus?</span>
          </h1>
          <p className="mb-10 mt-6 max-w-[560px] text-[17px] leading-[27px] text-white/70">
            Gib eine Adresse ein. LAST schickt erst eine, dann Hunderte simulierte Personen los – und sagt dir in einfachen Worten, für wie
            viele es reicht.
          </p>
          <NewTestForm
            defaults={defaults?.defaults ?? FALLBACK_DEFAULTS}
            quick={defaults?.quick ?? FALLBACK_QUICK}
            web={defaults?.web ?? FALLBACK_WEB}
            api={defaults?.api ?? FALLBACK_API}
            flow={defaults?.flow ?? FALLBACK_FLOW}
          />
        </div>

        <aside aria-label="Letzter Lauf" className="flex flex-col items-center gap-8 lg:pt-2">
          <div className="relative hidden w-full max-w-[600px] lg:block">
            <Nutzerstrom />
            {cap?.users != null && (
              <p className="absolute right-0 top-[14%] rounded-[14px] border border-[#a68cff]/40 bg-[#0a0b14]/80 px-4 py-3 shadow-[0_12px_32px_rgb(124_92_255/0.35)] backdrop-blur-[20px]">
                <span className="block font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-white/65">Letzter Lauf</span>
                <span className="mt-1 block font-display text-base font-bold">
                  <span aria-hidden="true" className="text-mint">
                    ●
                  </span>{" "}
                  {nf(cap.users, 0)} {last ? terms(last.summary.config).capacityUnit : "Nutzer"} möglich
                </span>
              </p>
            )}
            {best != null && (
              <p className="absolute bottom-[13%] left-[2%] rounded-[14px] border border-cyan/40 bg-[#0a0b14]/80 px-4 py-3 shadow-[0_12px_32px_rgb(34_211_238/0.3)] backdrop-blur-[20px]">
                <span className="block font-mono text-[9px] font-bold uppercase tracking-[0.14em] text-white/65">Bestwert</span>
                <span className="mt-1 block font-display text-base font-bold">
                  {secs(best)} {lastKind === "api" || lastKind === "flow" ? "bis die Antwort da ist" : lastIsWeb ? "bis die Seite da ist" : "bis zum 1. Wort"}
                </span>
              </p>
            )}
          </div>

          {last && verdict && (
            <section
              aria-labelledby="zuletzt-titel"
              className="card grid w-full max-w-[500px] grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-3 px-6 py-5"
            >
              <div className="min-w-0">
                <h2 id="zuletzt-titel" className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-white/65">
                  Zuletzt getestet
                </h2>
                <p className="mt-1.5 truncate font-display text-lg font-bold">
                  {hostLabel(last.summary.config.base_url)}
                  {last.summary.config.model ? ` · ${last.summary.config.model}` : ""}
                </p>
                <p className="mt-1 text-xs text-white/65">
                  {runLabel(last.run.name)}
                  {duration != null && ` · ${clock(duration)} min`}
                </p>
              </div>
              <Sparkline values={curvePoints(last.summary).map((p) => p.tps)} color="#8B8CFF" className="h-14 w-44 self-center" />
              <p className={`text-xs font-semibold ${VERDICT_STYLE[verdict.status]}`}>
                <span aria-hidden="true">● </span>
                {verdict.title.replace(".", "")}
              </p>
              <Link href={`/laeufe/${last.run.name}`} className="justify-self-end text-xs font-semibold text-cyan hover:underline">
                Ergebnis ansehen <span aria-hidden="true">→</span>
              </Link>
            </section>
          )}
        </aside>
      </main>
    </>
  );
}
