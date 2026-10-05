import Link from "next/link";
import { Meter } from "@/components/Meter";
import { ampelRows, capacityView, costView, kpiCards, sloSeconds, terms, verdictView, type KpiCard, type Status } from "@/lib/derive";
import { nf, secs, signedPct } from "@/lib/format";
import type { Summary } from "@/lib/types";

const TONE = {
  good: { word: "Grün", a: "#6EE7B7", b: "#059669", glow: "#34D399", text: "text-mint-soft", title: "to-mint-soft" },
  warn: { word: "Gelb", a: "#FCD34D", b: "#D97706", glow: "#FBBF24", text: "text-amber-soft", title: "to-amber-soft" },
  bad: { word: "Rot", a: "#FDA4AF", b: "#E11D48", glow: "#F43F5E", text: "text-rose-soft", title: "to-rose-soft" },
  none: { word: "Nicht getestet", a: "#CBD5E1", b: "#64748B", glow: "#94A3B8", text: "text-white/70", title: "to-white/70" },
} as const;

const CARD_TONE: Record<Status, string> = {
  good: "border-mint/50 from-mint/20 via-[#3499b2]/[0.07] to-violet/15 shadow-[0_24px_80px_rgb(52_211_153/0.22)]",
  warn: "border-amber/50 from-amber/20 via-amber/[0.05] to-violet/15 shadow-[0_24px_80px_rgb(251_191_36/0.18)]",
  bad: "border-rose/50 from-rose/20 via-rose/[0.05] to-violet/15 shadow-[0_24px_80px_rgb(244_63_94/0.2)]",
  none: "border-white/15 from-white/10 via-white/[0.03] to-violet/15",
};

/** Die Plakette aus dem Entwurf – Symbol je nach Urteil (Haken, Ausrufezeichen, Kreuz). */
function Badge({ status }: { status: Status }) {
  const t = TONE[status];
  return (
    <svg viewBox="0 0 220 220" className="size-36 shrink-0 md:size-[220px]" aria-hidden="true">
      <defs>
        <radialGradient id="plakette-glow">
          <stop stopColor={t.glow} stopOpacity="0.55" />
          <stop offset="0.6" stopColor={t.glow} stopOpacity="0.12" />
          <stop offset="1" stopColor={t.glow} stopOpacity="0" />
        </radialGradient>
        <linearGradient id="plakette-fill" x1="52" y1="52" x2="168" y2="168" gradientUnits="userSpaceOnUse">
          <stop stopColor={t.a} />
          <stop offset="1" stopColor={t.b} />
        </linearGradient>
      </defs>
      <circle cx="110" cy="110" r="110" fill="url(#plakette-glow)" />
      <circle
        cx="110"
        cy="110"
        r="86"
        fill="none"
        stroke={t.a}
        strokeOpacity="0.8"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray="2 10"
      />
      <circle cx="110" cy="110" r="70" fill="none" stroke={t.glow} strokeOpacity="0.3" />
      <circle cx="110" cy="110" r="58" fill="url(#plakette-fill)" stroke="#fff" strokeOpacity="0.35" />
      <ellipse cx="98" cy="86" rx="30" ry="16" fill="#fff" fillOpacity="0.18" />
      <g fill="none" stroke="#fff" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round">
        {status === "good" && <path d="M84 112l18 18 36-38" />}
        {status === "warn" && <path d="M110 84v30M110 136v.5" />}
        {status === "bad" && <path d="M90 90l40 40M130 90l-40 40" />}
        {status === "none" && <path d="M94 110h32" />}
      </g>
    </svg>
  );
}

const ICONS: Record<KpiCard["key"], { box: string; path: React.ReactNode }> = {
  alone: { box: "bg-cyan/15", path: <path d="M15.5 6l-6 9h4.5l-1.5 7 6-9H14z" fill="#22D3EE" /> },
  sweet: {
    box: "bg-violet/20",
    path: (
      <>
        <circle cx="14" cy="14" r="7" fill="none" stroke="#A5B4FC" strokeWidth="1.6" />
        <circle cx="14" cy="14" r="2.5" fill="#A5B4FC" />
      </>
    ),
  },
  peak: {
    box: "bg-pink/15",
    path: <path d="M7 19l5-6 3 3 6-7" fill="none" stroke="#F9A8D4" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />,
  },
  quality: {
    box: "bg-mint/15",
    path: <path d="M9 14.5l3.5 3.5 7-7.5" fill="none" stroke="#6EE7B7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />,
  },
};

function CapacityBar({ users, target }: { users: number; target: number }) {
  // Lage des Bedarfs-Strichs und des Kapazitäts-Endes kommt aus capacityView (0–1) → SVG-Koordinaten 0–400
  return (
    <svg viewBox="0 0 400 48" className="mt-4 h-12 w-full max-w-[400px]" aria-hidden="true">
      <defs>
        <linearGradient id="kap-fill" x1="0" x2={Math.max(users * 400, 1)} y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop stopColor="#34D399" />
          <stop offset="1" stopColor="#22D3EE" />
        </linearGradient>
      </defs>
      <rect y="18" width="400" height="12" rx="6" fill="#fff" fillOpacity="0.08" />
      <rect y="18" width={users * 400} height="12" rx="6" fill="url(#kap-fill)" />
      <circle cx={Math.max(users * 400 - 6, 6)} cy="24" r="4" fill="#fff" />
      {target > 0 && (
        <>
          <line x1={target * 400} x2={target * 400} y1="8" y2="42" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
          <circle cx={target * 400} cy="6" r="3" fill="#fff" />
        </>
      )}
    </svg>
  );
}

/** Bei Websites statt des Kostenvergleichs: was der Test genau getan hat – und was nicht. */
function MeasuredCard({ summary }: { summary: Summary }) {
  const pre = summary.prechecks;
  const cfg = summary.config;
  return (
    <section aria-labelledby="gemessen-titel" className="card p-7">
      <h2 id="gemessen-titel" className="font-display text-xl font-bold">
        Was wurde gemessen?
      </h2>
      <p className="mt-1 text-[13px] text-white/65">Damit klar ist, was die Zahlen bedeuten</p>
      <ul className="mt-4 flex list-disc flex-col gap-3 pl-5 text-sm leading-[21px] text-white/80">
        <li>
          Jeder simulierte Gast lädt die Seite
          {pre?.assets ? ` und ${pre.assets} Dateien derselben Website (Bilder, Styles, Skripte)` : " – ohne zugehörige Dateien"}.
          {pre?.total_bytes && pre.total_bytes >= 1024
            ? ` Ein Besuch wiegt zusammen rund ${nf(pre.total_bytes / 1024, 0)} kB.`
            : ""}
        </li>
        <li>Wie beim ersten Besuch: ohne Browser-Cache und mit eigenen Verbindungen. Wer wiederkommt, hat es eher leichter.</li>
        <li>
          Nicht gemessen: Inhalte fremder Server (zum Beispiel Schriften, Karten, Werbung) und die Zeit, die der Browser zum Darstellen
          braucht.
        </li>
        <li>
          Ziel: Seite nach höchstens {secs(sloSeconds(cfg))} geladen · Pause zwischen zwei Klicks: {nf(cfg.think_time, 0)} s
        </li>
      </ul>
    </section>
  );
}

export function ResultView({ name, summary, report, pdf }: { name: string; summary: Summary; report: boolean; pdf: boolean }) {
  const verdict = verdictView(summary);
  const cap = capacityView(summary);
  const cost = costView(summary);
  const web = summary.config.kind === "web";
  const people = terms(summary.config).people;
  const rows = ampelRows(summary);
  const tone = TONE[verdict.status];
  const files = `/api/runs/${name}`;
  const extraReasons = verdict.reasons.filter(([t]) => t !== "good" || verdict.status !== "good").slice(0, 4);

  return (
    <div className="flex flex-col gap-6">
      <section
        aria-labelledby="urteil-titel"
        className={`rounded-[28px] border bg-gradient-to-r p-6 backdrop-blur-[40px] md:p-9 ${CARD_TONE[verdict.status]}`}
      >
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)]">
          <div className="flex flex-col items-start gap-6 md:flex-row md:items-center md:gap-7">
            <Badge status={verdict.status} />
            <div className="min-w-0">
              <p className={`eyebrow ${tone.text}`}>Urteil{cap.target != null ? ` · für ${nf(cap.target, 0)} ${people} geplant` : ""}</p>
              <h1
                id="urteil-titel"
                className={`mt-1 bg-gradient-to-r from-white bg-clip-text font-display text-5xl font-bold tracking-[-0.03em] text-transparent md:text-[64px] md:leading-[1.25] ${tone.title}`}
              >
                {verdict.title}
              </h1>
              <p className="max-w-xl text-base leading-[25px] text-white/75">{verdict.text}</p>
              {extraReasons.length > 0 && (
                <ul className="mt-2 max-w-xl list-disc pl-5 text-sm leading-6 text-white/75">
                  {extraReasons.map(([, reason]) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
              <div className="mt-4 flex flex-wrap gap-3">
                {report && (
                  <a
                    href={`${files}/report.pptx`}
                    download
                    className="inline-flex min-h-[44px] items-center gap-2.5 rounded-xl bg-gradient-to-r from-mint to-cyan px-5 text-sm font-semibold text-[#04120d] shadow-[0_8px_24px_rgb(52_211_153/0.45)] hover:brightness-110"
                  >
                    <span aria-hidden="true">↓</span> PowerPoint herunterladen
                  </a>
                )}
                {pdf && (
                  <a href={`${files}/report.pdf`} download className="btn btn-ghost min-h-[44px] px-5 text-sm">
                    PDF · 1 Seite
                  </a>
                )}
                <a href={`${files}/raw_requests.jsonl`} download className="btn btn-ghost min-h-[44px] px-5 text-sm">
                  Rohdaten
                </a>
                <Link href="/laeufe" className="btn btn-ghost min-h-[44px] px-5 text-sm">
                  <span aria-hidden="true">⇄</span> Vergleichen
                </Link>
              </div>
            </div>
          </div>

          <div className="border-white/10 lg:border-l lg:pl-10">
            <h2 className="eyebrow text-white/65">Wie viele passen drauf?</h2>
            <p className="mt-1 flex flex-wrap items-center gap-x-8">
              <span className="bg-gradient-to-b from-white to-[#99ebff] bg-clip-text font-display text-[88px] font-bold leading-[1.1] tracking-[-0.04em] text-transparent [filter:drop-shadow(0_0_36px_rgb(34_211_238/0.45))]">
                {cap.users != null ? nf(cap.users, 0) : "–"}
              </span>
              <span className="text-[15px] font-medium leading-[22px] text-white/75">
                {web ? "Besucher gleichzeitig" : "aktive Nutzer"}
                <br />
                {web ? "möglich" : "im Team möglich"}
              </span>
            </p>
            {cap.users != null && <CapacityBar users={cap.usersFraction} target={cap.targetFraction} />}
            <p className="mt-1 flex flex-wrap gap-x-6 font-mono text-[11px]">
              {cap.target != null && <span className="font-bold text-white/85">Bedarf {nf(cap.target, 0)}</span>}
              {cap.users != null && (
                <span className="font-medium text-cyan">
                  Kapazität {nf(cap.users, 0)}
                  {cap.reservePct != null && ` · ${signedPct(cap.reservePct)} ${cap.reservePct >= 0 ? "Reserve" : "zu wenig"}`}
                </span>
              )}
              {cap.users == null && <span className="text-white/70">Ohne Lasttest keine Schätzung.</span>}
            </p>
          </div>
        </div>
      </section>

      <section aria-label="Kennzahlen" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpiCards(summary).map((k) => (
          <article
            key={k.key}
            className="relative rounded-[20px] border border-white/[0.08] bg-gradient-to-b from-white/[0.06] to-white/[0.02] p-6 backdrop-blur-[30px]"
          >
            <h2 className="eyebrow text-white/65">{k.label}</h2>
            <span aria-hidden="true" className={`absolute right-5 top-5 grid size-7 place-items-center rounded-lg ${ICONS[k.key].box}`}>
              <svg viewBox="0 0 28 28" className="size-7">
                {ICONS[k.key].path}
              </svg>
            </span>
            <p className="mt-1">
              <span className="font-display text-[44px] font-bold leading-[1.25] tracking-[-0.03em]">{k.value}</span>{" "}
              <span className="font-display text-[22px] font-bold tracking-[-0.03em] text-white/60">{k.unit}</span>
            </p>
            <p className="mt-1 text-[13px] leading-[19px] text-white/70">{k.text}</p>
          </article>
        ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <section aria-labelledby="ampel-titel" className="card p-7">
          <h2 id="ampel-titel" className="font-display text-xl font-bold">
            Alle Ergebnisse auf einen Blick
          </h2>
          <p className="mt-1 text-[13px] text-white/65">Grün = Ziel erreicht · Gelb = geht, aber spürbar · Rot = Problem</p>
          <ul aria-label="Alle Ergebnisse auf einen Blick" className="mt-4 divide-y divide-white/[0.06]">
            {rows.map((r) => (
              <li
                key={r.label}
                className="grid min-h-10 grid-cols-[18px_minmax(0,1fr)] items-center gap-x-4 py-2 sm:grid-cols-[18px_minmax(0,1.5fr)_minmax(0,1fr)]"
              >
                <svg viewBox="0 0 18 18" className="size-[18px]" aria-hidden="true">
                  <circle cx="9" cy="9" r="9" fill={TONE[r.status].glow} fillOpacity="0.2" />
                  <circle cx="9" cy="9" r="4.5" fill={TONE[r.status].glow} />
                </svg>
                <span className="text-sm font-medium text-white/90">
                  {r.label}
                  <span className="sr-only"> – {TONE[r.status].word}:</span>
                </span>
                <span
                  className={`col-start-2 font-mono text-[13px] font-medium sm:col-start-3 ${r.status === "good" ? "text-white/70" : TONE[r.status].text}`}
                >
                  {r.value}
                </span>
              </li>
            ))}
          </ul>
        </section>

        {web ? (
          <MeasuredCard summary={summary} />
        ) : (
          <section aria-labelledby="kosten-titel" className="card p-7">
            <h2 id="kosten-titel" className="font-display text-xl font-bold">
              Lohnt sich der eigene Server?
            </h2>
            {!cost ? (
              <p className="mt-2 text-[13px] text-white/70">Dafür fehlen die Lasttests – ohne Messwerte lässt sich nichts ausrechnen.</p>
            ) : (
              <>
                <p className="mt-1 text-[13px] text-white/65">Kosten pro 1.000 Antworten bei voller Auslastung</p>
                <dl className="mt-5 flex flex-col gap-5">
                  {[
                    { label: "Eigener Server", value: cost.own, f: cost.ownFraction, g: "mint" as const, text: "text-mint-soft" },
                    {
                      label: "Cloud, gleiches Modell",
                      value: cost.cloud,
                      f: cost.cloudFraction,
                      g: "rose" as const,
                      text: "text-pink-soft",
                    },
                  ].map((b) => (
                    <div key={b.label}>
                      <dt className="text-[13px] font-medium text-white/75">{b.label}</dt>
                      <dd className="mt-1.5 flex items-center gap-3">
                        <span className="block min-w-0 flex-1">
                          <Meter value={b.f} label={b.label} gradient={b.g} className="h-5 !rounded-md !bg-transparent" decorative />
                        </span>
                        <span className={`w-20 shrink-0 text-right font-mono text-[15px] font-bold ${b.text}`}>{b.value}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
                <div className="mt-7 grid gap-6 border-t border-white/[0.07] pt-5 sm:grid-cols-2">
                  <div>
                    <h3 className="eyebrow text-white/65">{cost.saves ? "Ersparnis bei eurem Bedarf" : "Mehrkosten bei eurem Bedarf"}</h3>
                    {cost.savings ? (
                      <>
                        <p
                          className={`bg-gradient-to-r bg-clip-text font-display text-5xl font-bold leading-[1.3] tracking-[-0.03em] text-transparent ${
                            cost.saves ? "from-mint-soft to-cyan" : "from-amber-soft to-rose-soft"
                          }`}
                        >
                          {cost.savings}
                        </p>
                        <p className="text-[13px] font-medium text-white/70">pro Monat</p>
                      </>
                    ) : (
                      <p className="mt-2 text-[13px] text-white/70">
                        Tragt beim nächsten Test ein, wie viele Nutzer ihr habt – dann steht hier ein Betrag.
                      </p>
                    )}
                  </div>
                  <div>
                    <h3 className="eyebrow text-white/65">Lohnt sich ab</h3>
                    <p className="mt-1 font-display">
                      <span className="text-[28px] font-bold">{cost.breakeven}</span>{" "}
                      <span className="text-base font-bold text-white/60">Auslastung</span>
                    </p>
                    {cost.needPct != null && <p className="text-[13px] font-medium text-mint-soft">Euer Bedarf: ≈ {cost.needPct} %</p>}
                    {cost.placeholder && (
                      <p className="mt-2.5 rounded-lg border border-amber/35 bg-amber/10 px-2.5 py-1.5 text-[11px] font-medium text-amber-soft">
                        <span aria-hidden="true">⚠ </span>Preise sind Platzhalter – bitte eintragen
                      </p>
                    )}
                  </div>
                </div>
              </>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
