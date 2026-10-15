"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { freePlaceholder, parseLine, withStart } from "@/lib/steps";
import type { LiveElement, LiveReply, LiveSnapshot, LiveTarget } from "@/lib/types";

type Ask = { target: LiveTarget; thumb: string | null; text: string; secret: boolean; name: string; enter: boolean };

const ACTION: Record<LiveElement["kind"], string> = { field: "Eingeben in", button: "Klicken auf", link: "Klicken auf", check: "Klicken auf" };

async function call(op: "start" | "act" | "stop", body: unknown): Promise<LiveReply & { error?: LiveReply["error"] }> {
  try {
    const res = await fetch(`/api/flow/live/${op}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    return (await res.json()) as LiveReply;
  } catch {
    return { error: "Keine Verbindung zur Oberfläche. Läuft der Container noch?" };
  }
}

/** Fokus bleibt im Fenster: Tab am Ende springt an den Anfang und umgekehrt. */
function trapTab(e: React.KeyboardEvent<HTMLElement>) {
  if (e.key !== "Tab") return;
  const all = [...e.currentTarget.querySelectorAll<HTMLElement>("button, input, select, textarea, [href]")].filter(
    (el) => !el.hasAttribute("disabled") && el.tabIndex !== -1,
  );
  if (!all.length) return;
  const [first, last] = [all[0], all[all.length - 1]];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

export function LiveRecorder({
  text,
  baseUrl,
  secrets,
  sidebar,
  onAppend,
  onTruncate,
  onSecret,
  onFailed,
  onClose,
}: {
  /** der Ablauf als Text – Quelle der Wahrheit, gehört dem Formular */
  text: string;
  baseUrl: string;
  secrets: Record<string, string>;
  /** der grafische Ablauf, links neben der Seite */
  sidebar: ReactNode;
  onAppend: (lines: string[], thumb: string | null) => string;
  /** Schritte ab dieser Stelle (unter den ausgeführten) entfernen; liefert den neuen Text */
  onTruncate: (executedIndex: number) => string;
  onSecret: (name: string, value: string) => void;
  /** Schritt (unter den ausgeführten), an dem das Abspielen hängen blieb – oder null */
  onFailed: (executedIndex: number | null) => void;
  onClose: () => void;
}) {
  const [session, setSession] = useState<string | null>(null);
  const [snap, setSnap] = useState<LiveSnapshot | null>(null);
  // Fehlen Zugangsdaten, fragt das Fenster erst danach – sonst startet es sofort
  const [busy, setBusy] = useState<string | null>(() =>
    [...text.matchAll(/\{([A-Za-z_][\w-]*)\}/g)].some((m) => !secrets[m[1]]) ? null : "Der Browser öffnet die Seite …",
  );
  const [message, setMessage] = useState<{ tone: "bad" | "info"; text: string } | null>(null);
  const [failedAt, setFailedAt] = useState<number | null>(null);
  const [ask, setAsk] = useState<Ask | null>(null);
  // Stand des Ablaufs, den der Browser gerade zeigt – weicht der Text ab, muss neu abgespielt werden
  const [synced, setSynced] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const sessionRef = useRef<string | null>(null);

  const lines = text.split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith("#"));
  const used = [...new Set([...text.matchAll(/\{([A-Za-z_][\w-]*)\}/g)].map((m) => m[1]))];
  const missing = used.filter((p) => !secrets[p]);
  // Welche Zugangsdaten beim Öffnen fehlten – das Formular dafür bleibt stehen, bis man startet
  const [asking, setAsking] = useState<string[]>(missing);
  const measuring = lines.some((l) => parseLine(l).kind === "measure");
  const stale = synced !== null && synced !== text;

  async function start(current = text) {
    setBusy("Der Browser öffnet die Seite und spielt den Ablauf ab …");
    setMessage(null);
    setFailedAt(null);
    onFailed(null);
    setAsk(null);
    const r = await call("start", { steps: withStart(current, baseUrl), secrets });
    setBusy(null);
    if (!r.session || !r.snapshot) {
      setMessage({ tone: "bad", text: typeof r.error === "string" ? r.error : "Der Browser ließ sich nicht starten." });
      return;
    }
    sessionRef.current = r.session;
    setSession(r.session);
    setSnap(r.snapshot);
    setSynced(current);
    if (r.error && typeof r.error === "object") {
      // Die Startseite zählt beim Backend mit, wenn der Ablauf nicht selbst mit „öffne“ beginnt
      const own = /^\s*öffne\s/i.test(current);
      const at = r.error.index - (own ? 0 : 1);
      setFailedAt(at);
      onFailed(at);
      setMessage({ tone: "bad", text: `Schritt ${at + 1}: ${r.error.message}` });
    }
  }

  useEffect(() => {
    heading.current?.focus();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Browser einmal beim Öffnen starten (Netzwerk, kein abgeleiteter Zustand)
    if (!missing.length) void start();
    return () => {
      if (sessionRef.current) void call("stop", {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- nur beim Öffnen
  }, []);

  function apply(r: LiveReply) {
    if (r.snapshot) setSnap(r.snapshot);
    if (typeof r.error === "string") {
      setMessage({ tone: "bad", text: r.error });
      return;
    }
    setMessage(null);
    if (r.steps?.length) {
      setSynced(onAppend(r.steps, r.thumb ?? null));
      if (r.steps.some((l) => parseLine(l).kind === "wait_quiet")) {
        setMessage({ tone: "info", text: "Die Seite hat noch geschrieben – „Warten, bis die Seite fertig ist“ ist im Ablauf ergänzt." });
      }
    }
  }

  async function act(action: Record<string, unknown>, extraSecrets: Record<string, string> = {}, label = "Der Browser arbeitet …") {
    if (!session) return;
    setBusy(label);
    const r = await call("act", { session, action: { ...action, measuring }, secrets: { ...secrets, ...extraSecrets } });
    setBusy(null);
    // Sitzung abgelaufen (oder Browser nach einer Zeitüberschreitung geschlossen): neu starten anbieten
    if (typeof r.error === "string" && /geschlossen/.test(r.error)) setSession(null);
    if (r.need === "text" && r.target) {
      const secret = !!r.target.secret;
      setAsk({
        target: r.target,
        thumb: r.thumb ?? null,
        text: "",
        secret,
        name: freePlaceholder(r.target.secret ?? r.target.label.toLowerCase(), used),
        enter: false,
      });
      return;
    }
    apply(r);
  }

  function pick(el: LiveElement) {
    if (busy || stale || ask) return;
    void act({ type: "pick", mark: el.mark }, {}, el.kind === "field" ? "Einen Moment …" : `Klickt auf „${el.label || "…"}“ …`);
  }

  function submitAsk(e: FormEvent) {
    e.preventDefault();
    if (!ask) return;
    const { target, secret, name, text: value, enter } = ask;
    const where = { target: target.target, ...(target.near ? { near: target.near } : {}), ...(target.nth ? { nth: target.nth } : {}) };
    setAsk(null);
    if (secret) onSecret(name, value);
    void act({ type: "fill", target: where, text: secret ? `{${name}}` : value, enter }, secret ? { [name]: value } : {}, "Tippt …");
  }

  function markHere() {
    const next = onAppend(["messen ab hier"], null);
    setSynced(next);
    setMessage({ tone: "info", text: "Ab jetzt wird gemessen. Führe vor, was unter Last wiederholt werden soll." });
  }

  const pct = (v: number, of: number) => `${(v / of) * 100}%`;
  const vp = snap?.viewport ?? { w: 1280, h: 800 };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-ink/95 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="vorfuehren-titel"
        onKeyDown={(e) => {
          if (e.key === "Escape" && !ask) onClose();
          trapTab(e);
        }}
        className="mx-auto flex min-h-full max-w-[1500px] flex-col gap-4 p-4 sm:p-6"
      >
        <header className="flex flex-wrap items-center gap-3">
          <div className="flex-1">
            <h2 id="vorfuehren-titel" ref={heading} tabIndex={-1} className="font-display text-2xl font-bold focus:outline-none">
              Ablauf vorführen
            </h2>
            <p className="text-sm text-white/70">Klick in die Seite, so wie ein Mensch es tun würde. Jeder Klick wird sofort ausgeführt.</p>
          </div>
          <button type="button" className="btn btn-primary min-h-11 px-6 text-sm" onClick={onClose}>
            Fertig
          </button>
        </header>

        <div className="grid flex-1 gap-4 lg:grid-cols-[minmax(300px,380px)_1fr]">
          <aside aria-label="Der Ablauf bisher" className="order-2 lg:order-1 lg:max-h-[calc(100vh-140px)] lg:overflow-y-auto">
            {sidebar}
          </aside>

          <section aria-label="Die Seite" className="order-1 flex min-w-0 flex-col gap-3 lg:order-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="min-w-0 flex-1 truncate font-mono text-xs text-white/60">{snap?.url ?? baseUrl}</p>
              <button type="button" className="btn btn-ghost text-xs" disabled={!session || !!busy || stale} onClick={() => act({ type: "press", key: "Enter" }, {}, "Drückt Enter …")}>
                ↵ Enter drücken
              </button>
              <button type="button" className="btn btn-ghost text-xs" disabled={!session || !!busy || stale} onClick={() => act({ type: "press", key: "Tab" }, {}, "Drückt Tab …")}>
                ⇥ Tab
              </button>
              {!measuring && (
                <button type="button" className="btn btn-ghost border-cyan/50 text-xs text-cyan-soft" disabled={!!busy} onClick={markHere}>
                  ⏱ Ab hier messen
                </button>
              )}
              <button type="button" className="btn btn-ghost text-xs" disabled={!!busy} onClick={() => start()}>
                ⟳ Neu abspielen
              </button>
            </div>

            <div role="status" className="min-h-0 text-sm">
              {busy && <p className="text-white/75">{busy}</p>}
              {message && (
                <p className={`rounded-xl border px-3 py-2 ${message.tone === "bad" ? "border-rose/45 bg-rose/10 text-rose-soft" : "border-cyan/35 bg-cyan/[0.07] text-cyan-soft"}`}>
                  {message.text}
                </p>
              )}
              {stale && !busy && <p className="text-amber-soft">Der Ablauf wurde geändert – „⟳ Neu abspielen“, damit die Seite wieder dazu passt.</p>}
            </div>
            {failedAt !== null && !busy && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn btn-ghost text-xs"
                  onClick={() => {
                    const next = onTruncate(failedAt);
                    setSynced(next);
                    setFailedAt(null);
                    onFailed(null);
                    setMessage({ tone: "info", text: `Ab Schritt ${failedAt + 1} entfernt – mach einfach hier weiter.` });
                  }}
                >
                  Ab Schritt {failedAt + 1} neu vorführen
                </button>
              </div>
            )}

            {!session && !busy && asking.length > 0 && (
              <form
                className="tile grid gap-3 p-4 sm:grid-cols-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  setAsking([]);
                  void start();
                }}
              >
                <p className="text-sm sm:col-span-2">Zum Abspielen braucht der Browser noch die Zugangsdaten. Sie werden nicht gespeichert.</p>
                {asking.map((p) => (
                  <label key={p} className="text-xs text-white/70">
                    Wert für {`{${p}}`}
                    <input type="password" autoComplete="off" value={secrets[p] ?? ""} onChange={(e) => onSecret(p, e.target.value)} className="field mt-1" />
                  </label>
                ))}
                <button type="submit" className="btn btn-primary sm:col-span-2" disabled={asking.some((p) => !secrets[p])}>
                  Starten
                </button>
              </form>
            )}

            {ask && (
              <form onSubmit={submitAsk} className="tile grid gap-3 border-violet/50 p-4" aria-label={`Eingabe in „${ask.target.label}“`}>
                <div className="flex items-center gap-3">
                  {/* eslint-disable-next-line @next/next/no-img-element -- Ausschnitt kommt als data:-URL vom Backend */}
                  {ask.thumb && <img src={ask.thumb} alt="" className="max-h-12 max-w-48 rounded-md border border-white/10" />}
                  <label htmlFor="vorfuehren-text" className="flex-1 text-sm font-semibold">
                    Was soll in „{ask.target.label}“ hinein?
                  </label>
                </div>
                <input
                  id="vorfuehren-text"
                  autoFocus
                  type={ask.secret ? "password" : "text"}
                  autoComplete="off"
                  value={ask.text}
                  onChange={(e) => setAsk({ ...ask, text: e.target.value })}
                  className="field"
                />
                <label className="flex items-start gap-2.5 text-sm">
                  <input type="checkbox" checked={ask.secret} onChange={(e) => setAsk({ ...ask, secret: e.target.checked })} className="mt-0.5 size-5 accent-violet" />
                  <span>
                    Zugangsdaten – nicht speichern
                    <span className="block text-xs text-white/60">Im Ablauf steht dann nur {`{${ask.name}}`}; der Wert bleibt in diesem Fenster.</span>
                  </span>
                </label>
                <label className="flex items-center gap-2.5 text-sm">
                  <input type="checkbox" checked={ask.enter} onChange={(e) => setAsk({ ...ask, enter: e.target.checked })} className="size-5 accent-violet" />
                  Danach Enter drücken (zum Beispiel zum Absenden)
                </label>
                <div className="flex justify-end gap-2">
                  <button type="button" className="btn btn-ghost" onClick={() => setAsk(null)}>
                    Abbrechen
                  </button>
                  <button type="submit" className="btn btn-primary">
                    Eingeben
                  </button>
                </div>
              </form>
            )}

            <div className={`relative overflow-hidden rounded-2xl border border-white/15 bg-white ${busy ? "cursor-wait" : ""}`}>
              {snap?.screenshot ? (
                // eslint-disable-next-line @next/next/no-img-element -- Bild kommt als data:-URL vom Backend
                <img src={snap.screenshot} alt={`Die Seite ${snap.title || snap.url}`} className={`block w-full select-none ${busy || stale ? "opacity-50" : ""}`} draggable={false} />
              ) : (
                <div className="grid aspect-[16/10] place-items-center bg-ink-2 text-sm text-white/60">{busy ?? "Noch keine Seite"}</div>
              )}
              {snap &&
                !busy &&
                !stale &&
                !ask &&
                snap.elements.map((el) => (
                  <button
                    key={el.mark}
                    type="button"
                    onClick={() => pick(el)}
                    onMouseEnter={() => setHover(el.mark)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(el.mark)}
                    onBlur={() => setHover(null)}
                    aria-label={`${ACTION[el.kind]} „${el.label || "ohne Beschriftung"}“`}
                    style={{ left: pct(el.box.x, vp.w), top: pct(el.box.y, vp.h), width: pct(el.box.w, vp.w), height: pct(el.box.h, vp.h) }}
                    className="absolute rounded-[5px] outline-none ring-cyan/0 transition hover:bg-cyan/15 hover:ring-2 hover:ring-cyan focus-visible:bg-cyan/15 focus-visible:ring-2 focus-visible:ring-cyan"
                  />
                ))}
              {snap && hover && !busy && (
                <HoverTip el={snap.elements.find((e) => e.mark === hover)} vp={vp} />
              )}
            </div>
            <p className="text-xs text-white/55">
              Felder und Knöpfe leuchten auf, wenn die Maus darüber ist. Mit der Tastatur: Tab springt von Element zu Element, Enter wählt aus.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

function HoverTip({ el, vp }: { el?: LiveElement; vp: { w: number; h: number } }) {
  if (!el) return null;
  const top = el.box.y > 40;
  return (
    <span
      aria-hidden="true"
      style={{ left: `${(el.box.x / vp.w) * 100}%`, top: `${((top ? el.box.y : el.box.y + el.box.h) / vp.h) * 100}%` }}
      className={`pointer-events-none absolute z-10 max-w-64 truncate rounded-md bg-ink px-2 py-1 text-[11px] font-semibold text-white shadow-lg ${top ? "-translate-y-[calc(100%+4px)]" : "translate-y-1"}`}
    >
      {ACTION[el.kind]} „{el.label || "…"}“
    </span>
  );
}
