"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { FALLBACK_API, FALLBACK_FLOW, FALLBACK_WEB } from "@/lib/profile";
import type { ModelInfo, RunKind } from "@/lib/types";
import { METHODS, parseBaseUrl, parseHeaderLines } from "@/lib/validation";

type Values = Record<string, unknown>;
type Profile = "quick" | "full";

// Nur diese Felder werden im Browser gemerkt. Bewusst nicht dabei: der API-Schlüssel
// und die Bestätigung, dass die Website getestet werden darf (die gilt nur für diesen einen Start).
const STORAGE_KEY = "last.form.v1";
const REMEMBERED = [
  "base_url",
  "model",
  "target_users",
  "slo_ttft",
  "slo_user_tps",
  "hw_price",
  "server_watts",
  "power_price",
  "cloud_price_in",
  "cloud_price_out",
  "web_url",
  "web_users",
  "slo_load",
  "think_time",
  "api_url",
  "api_rpm",
  "api_slo",
  "expect_status",
  "method",
  "flow_url",
  "flow_users",
  "flow_slo",
  "flow_think",
  // Die Schritte enthalten nur Platzhalter – die Werte dazu werden nie gemerkt
  "flow_steps",
] as const;

const PLACEHOLDER_RE = /\{([a-zA-Z][a-zA-Z0-9_]{0,31})\}/g;

/** Alle {platzhalter} in den Schritten, in Reihenfolge des ersten Auftretens. */
export function findPlaceholders(steps: string): string[] {
  return [...new Set([...steps.matchAll(PLACEHOLDER_RE)].map((m) => m[1]))];
}

const STEP_EXAMPLE = `tippe in "E-Mail" {email}
tippe in "Passwort" {passwort}
klicke "Anmelden"
warte auf Text "Willkommen"
messen ab hier
tippe in "Nachricht" "Was ist ein Lasttest?"
drücke Enter
warte bis ".antwort" fertig ist (2 s ruhig)`;

const STEP_WORDS: [string, string][] = [
  ['tippe in "Feld" Text', "Feld = Beschriftung, Platzhaltertext oder CSS-Selektor; {name} wird zum Passwortfeld"],
  ['klicke "Knopf"', "Knopf, Link oder Selektor"],
  ["drücke Enter", "oder Tab, Escape …"],
  ['warte auf Text "…"', "bis der Text irgendwo auf der Seite steht"],
  ['warte auf "…"', "bis das Element da ist"],
  ["warte 2 s", "einfach warten"],
  ["messen ab hier", "ab hier wird mitgeschnitten – genau einmal, danach mindestens ein Schritt"],
  ['warte auf erste Antwort in "…"', "misst, wann das erste Wort erscheint"],
  ['warte bis "…" fertig ist (2 s ruhig)', "fertig, wenn sich der Text so lange nicht mehr ändert"],
];

const COST_FIELDS = [
  { name: "hw_price", label: "Kaufpreis Server", unit: "€" },
  { name: "server_watts", label: "Stromverbrauch", unit: "Watt" },
  { name: "power_price", label: "Strompreis", unit: "€/kWh" },
  { name: "cloud_price_in", label: "Cloud: Eingabe", unit: "€ je 1 Mio. Tokens" },
  { name: "cloud_price_out", label: "Cloud: Ausgabe", unit: "€ je 1 Mio. Tokens" },
] as const;

type Target = { name: string; label: string; unit: string; step: string; min: string; placeholder: string; text?: boolean };

const TARGETS: Record<RunKind, Target[]> = {
  llm: [
    { name: "target_users", label: "Nutzer im Team", unit: "Personen", step: "1", min: "0", placeholder: "?" },
    { name: "slo_ttft", label: "Warten höchstens", unit: "Sekunden", step: "0.1", min: "0.1", placeholder: "2" },
    { name: "slo_user_tps", label: "Lesetempo mindestens", unit: "tok/s", step: "1", min: "1", placeholder: "10" },
  ],
  web: [
    { name: "web_users", label: "Besucher gleichzeitig", unit: "erwartet", step: "1", min: "0", placeholder: "?" },
    { name: "slo_load", label: "Seite geladen nach höchstens", unit: "Sekunden", step: "0.1", min: "0.1", placeholder: "3" },
    { name: "think_time", label: "Pause zwischen zwei Klicks", unit: "Sekunden", step: "1", min: "1", placeholder: "30" },
  ],
  api: [
    { name: "api_rpm", label: "Anfragen pro Minute", unit: "erwartet", step: "1", min: "0", placeholder: "?" },
    { name: "api_slo", label: "Antwort nach höchstens", unit: "Sekunden", step: "0.05", min: "0.05", placeholder: "0,5" },
    { name: "expect_status", label: "Erwarteter Status", unit: "z. B. 2xx", step: "1", min: "0", placeholder: "2xx", text: true },
  ],
  flow: [
    { name: "flow_users", label: "Nutzer gleichzeitig", unit: "erwartet", step: "1", min: "0", placeholder: "?" },
    { name: "flow_slo", label: "Antwort fertig nach höchstens", unit: "Sekunden", step: "0.5", min: "0.5", placeholder: "10" },
    { name: "flow_think", label: "Pause zwischen zwei Durchläufen", unit: "Sekunden", step: "1", min: "1", placeholder: "60" },
  ],
};

const KINDS: { value: RunKind; icon: string; label: string }[] = [
  { value: "llm", icon: "✦", label: "KI-Server" },
  { value: "api", icon: "{ }", label: "HTTP-API" },
  { value: "web", icon: "▦", label: "Website" },
  { value: "flow", icon: "⇶", label: "Ablauf" },
];

const THING: Record<RunKind, string> = { llm: "Server", web: "Website", api: "API", flow: "Anwendung" };
const THINGS: Record<RunKind, string> = { llm: "Server", web: "Websites", api: "APIs", flow: "Anwendungen" };
const URL_LABEL: Record<RunKind, string> = {
  llm: "Adresse des Servers",
  web: "Adresse der Website",
  api: "Adresse der API",
  flow: "Adresse der Startseite",
};
const URL_EXAMPLE: Record<RunKind, string> = {
  llm: "http://spark.buero.lan:8000/v1",
  web: "https://www.example.de/",
  api: "https://api.example.de/v1/items",
  flow: "https://chat.example.de/login",
};
const URL_HELP: Record<RunKind, string> = {
  llm: "Adresse eines OpenAI-kompatiblen Servers, beginnend mit http:// oder https://. Enter startet den Test.",
  web: "Adresse der Seite, die die simulierten Besucher aufrufen, beginnend mit http:// oder https://. Enter startet den Test.",
  api: "Adresse des Endpunkts, den die simulierten Aufrufer ansprechen, beginnend mit http:// oder https://. Enter startet den Test.",
  flow: "Die Seite, auf der der Ablauf beginnt – meist die Anmeldeseite –, beginnend mit http:// oder https://.",
};
const URL_FIELD: Record<RunKind, string> = { llm: "base_url", web: "web_url", api: "api_url", flow: "flow_url" };

type Check = { state: "idle" | "busy" } | { state: "ok"; models: ModelInfo[] } | { state: "fail"; message: string };

function text(v: unknown): string {
  return v == null || v === 0 ? "" : String(v);
}

function levelsInfo(levels: unknown): string {
  const list = String(levels ?? "")
    .split(",")
    .map(Number)
    .filter(Boolean);
  return list.length ? `${list.length} Stufen · bis ${Math.max(...list)} gleichzeitig` : "";
}

function minutes(v: Values, kind: RunKind): string {
  // Faustregel: Schnell ≈ 15 min, Gründlich ≈ 50 min; Websites und APIs haben keinen Test mit langen Texten,
  // Abläufe brauchen die Aufzeichnung im Browser und lange Antworten
  const quick = Number(v.soak_minutes) <= 5;
  if (kind === "llm") return quick ? "~15 min" : "~50 min";
  if (kind === "flow") return quick ? "~15 min" : "~40 min";
  return quick ? "~10 min" : "~35 min";
}

/** Werte des gewählten Profils: „Schnell“ kommt fertig vom Backend, „Gründlich“ sind die Standardwerte. */
function profileValues(profile: Profile, quick: Values, defaults: Values): Values {
  return profile === "quick" ? quick : Object.fromEntries(Object.keys(quick).map((k) => [k, defaults[k]]));
}

export function NewTestForm({
  defaults,
  quick,
  web = FALLBACK_WEB,
  api = FALLBACK_API,
  flow = FALLBACK_FLOW,
  features = { flow: true },
}: {
  defaults: Values;
  quick: Values;
  web?: { defaults: Values; quick: Values };
  api?: { defaults: Values; quick: Values };
  flow?: { defaults: Values; quick: Values };
  features?: { flow: boolean };
}) {
  const router = useRouter();
  const urlRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const moreId = useId();
  const [kind, setKind] = useState<RunKind>("llm");
  const [form, setForm] = useState<Record<string, string>>(() => ({
    base_url: text(defaults.base_url),
    model: "",
    api_key: "",
    target_users: text(defaults.target_users),
    slo_ttft: text(defaults.slo_ttft ?? 2),
    slo_user_tps: text(defaults.slo_user_tps ?? 10),
    ...Object.fromEntries(COST_FIELDS.map((f) => [f.name, text(defaults[f.name])])),
    web_url: "",
    web_users: "",
    slo_load: text(web.defaults.slo_load ?? 3),
    think_time: text(web.defaults.think_time ?? 30),
    api_url: "",
    api_rpm: "",
    api_slo: text(api.defaults.slo_load ?? 0.5),
    expect_status: "2xx",
    method: "GET",
    // Kopfzeilen und Body werden bewusst nicht gemerkt – sie enthalten oft Zugangsdaten
    headers_text: "",
    body_text: "",
    flow_url: "",
    flow_users: "",
    flow_slo: text(flow.defaults.slo_load ?? 10),
    flow_think: text(flow.defaults.think_time ?? 60),
    flow_steps: "",
  }));
  // Werte der Platzhalter: nur im Arbeitsspeicher, nie im localStorage
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [profile, setProfile] = useState<Profile>("quick");
  const [includeAssets, setIncludeAssets] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<Check>({ state: "idle" });

  const isWeb = kind === "web";
  const isApi = kind === "api";
  const isFlow = kind === "flow";
  const isLlm = kind === "llm";
  const urlField = URL_FIELD[kind];
  const writes = isApi && form.method !== "GET";
  const placeholders = isFlow ? findPlaceholders(form.flow_steps) : [];

  // Gemerkte Eingaben erst nach dem ersten Rendern einsetzen, damit Server- und Browser-HTML übereinstimmen.
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Record<string, string> | null;
      if (!saved || typeof saved !== "object") return;
      const { profile: savedProfile, kind: savedKind, ...rest } = saved;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- einmalige Übernahme aus localStorage
      setForm((f) => ({ ...f, ...Object.fromEntries(Object.entries(rest).filter(([, v]) => typeof v === "string" && v)) }));
      if (savedProfile === "full" || savedProfile === "quick") setProfile(savedProfile);
      if (savedKind === "web" || savedKind === "llm" || savedKind === "api" || (savedKind === "flow" && features.flow)) {
        setKind(savedKind);
      }
    } catch {
      // Gesperrter oder kaputter Speicher: einfach mit den Standardwerten weitermachen.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- nur einmal beim ersten Rendern
  }, []);

  const set = (name: string) => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [name]: e.target.value }));
    if (name === urlField) {
      setUrlError(null);
      setCheck({ state: "idle" });
    }
  };

  function chooseKind(next: RunKind) {
    setKind(next);
    setUrlError(null);
    setConfirmError(false);
    setServerError(null);
    setFormError(null);
  }

  function validUrl(): string | null {
    const url = parseBaseUrl(form[urlField]);
    if (!url) {
      setUrlError(`Die Adresse muss mit http:// oder https:// beginnen, zum Beispiel ${URL_EXAMPLE[kind]}`);
      urlRef.current?.focus();
    }
    return url;
  }

  async function post(path: string, body: unknown): Promise<{ ok: boolean; data: Record<string, unknown> }> {
    try {
      const res = await fetch(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      return { ok: res.ok, data: (await res.json()) as Record<string, unknown> };
    } catch {
      return { ok: false, data: { error: "Keine Verbindung zur Oberfläche. Läuft der Container noch?" } };
    }
  }

  async function checkConnection() {
    const base_url = validUrl();
    if (!base_url) return;
    setCheck({ state: "busy" });
    const { ok, data } = await post("/api/models", { base_url, api_key: form.api_key || undefined });
    if (!ok) return setCheck({ state: "fail", message: String(data.error ?? "nicht erreichbar") });
    const models = (data.models as ModelInfo[]) ?? [];
    setCheck({ state: "ok", models });
    if (!form.model && models[0]) setForm((f) => ({ ...f, model: models[0].id }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    setFormError(null);
    setConfirmError(false);
    const base_url = validUrl();
    if (!base_url) return;
    if (!isLlm && !confirmed) {
      setConfirmError(true);
      confirmRef.current?.focus();
      return;
    }
    let steps = "";
    if (isFlow) {
      const own = form.flow_steps.trim();
      if (!own) {
        setFormError("Bitte die Schritte aufschreiben – mindestens „messen ab hier“ und einen Schritt danach.");
        return;
      }
      const missing = placeholders.filter((p) => !secrets[p]);
      if (missing.length) {
        setFormError(`Bitte den Wert für {${missing[0]}} eintragen.`);
        return;
      }
      // Die Startseite steht oben – wer selbst mit „öffne“ anfängt, behält seine Zeile
      steps = /^öffne\s/i.test(own) ? own : `öffne ${base_url}\n${own}`;
    }

    const number = (name: string) => (form[name] === "" ? undefined : Number(form[name].replace(",", ".")));
    let headers: { name: string; value: string }[] = [];
    if (isApi) {
      try {
        headers = parseHeaderLines(form.headers_text);
      } catch (err) {
        setFormError(err instanceof Error ? err.message : "Kopfzeilen prüfen");
        return;
      }
    }
    const payload = isFlow
      ? {
          ...profileValues(profile, flow.quick, flow.defaults),
          kind: "flow",
          base_url,
          steps,
          secrets: Object.fromEntries(placeholders.map((p) => [p, secrets[p]])),
          confirm_owner: true,
          tests: String(flow.defaults.tests ?? "baseline,ramp,rate,spike,soak"),
          target_users: number("flow_users") ?? 0,
          slo_load: number("flow_slo"),
          think_time: number("flow_think"),
        }
      : isApi
      ? {
          ...profileValues(profile, api.quick, api.defaults),
          kind: "api",
          base_url,
          method: form.method,
          headers,
          body: writes ? form.body_text : "",
          expect_status: form.expect_status.trim() || "2xx",
          confirm_owner: true,
          tests: String(api.defaults.tests ?? "baseline,ramp,rate,spike,soak"),
          target_users: number("api_rpm") ?? 0,
          slo_load: number("api_slo"),
        }
      : isWeb
        ? {
            ...profileValues(profile, web.quick, web.defaults),
            kind: "web",
            base_url,
            confirm_owner: true,
            include_assets: includeAssets,
            tests: String(web.defaults.tests ?? "baseline,ramp,rate,spike,soak"),
            target_users: number("web_users") ?? 0,
            slo_load: number("slo_load"),
            think_time: number("think_time"),
          }
        : {
            ...profileValues(profile, quick, defaults),
            base_url,
            model: form.model || undefined,
            api_key: form.api_key || undefined,
            target_users: number("target_users") ?? 0,
            slo_ttft: number("slo_ttft"),
            slo_user_tps: number("slo_user_tps"),
            ...Object.fromEntries(COST_FIELDS.map((f) => [f.name, number(f.name)])),
          };

    setBusy(true);
    const { ok, data } = await post("/api/start", payload);
    if (!ok) {
      setBusy(false);
      setServerError(String(data.error ?? "Der Test konnte nicht gestartet werden."));
      return;
    }
    try {
      const remembered = { ...Object.fromEntries(REMEMBERED.map((k) => [k, form[k]])), profile, kind };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(remembered));
    } catch {
      // Merken ist nur Komfort.
    }
    router.push("/lauf");
  }

  const source = isFlow ? flow : isApi ? api : isWeb ? web : { defaults, quick };
  const profiles: { key: Profile; title: string; values: Values; hint: string }[] = [
    { key: "quick", title: "Schnell", values: source.quick, hint: "für einen ersten Eindruck" },
    { key: "full", title: "Gründlich", values: source.defaults, hint: "für die Entscheidung" },
  ];
  const urlLabel = URL_LABEL[kind];
  const thing = THING[kind];
  const legend = "mb-2 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-white/65";
  const focusRing =
    "has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-cyan";

  return (
    <form onSubmit={onSubmit} noValidate className="flex max-w-[600px] flex-col gap-7">
      <div>
        <div className="relative rounded-2xl bg-gradient-to-r from-[#9980ff]/90 to-cyan/70 p-[1.5px] shadow-[0_0_40px_rgb(124_92_255/0.35)]">
          <div className="flex min-h-16 flex-wrap items-center gap-x-3 gap-y-1 rounded-[15px] bg-[#08090f]/90 py-2 pl-5 pr-3">
            <label htmlFor="base_url" className="flex items-center">
              <span aria-hidden="true" className="text-lg text-cyan">
                ◎
              </span>
              <span className="sr-only">{urlLabel}</span>
            </label>
            {isApi && (
              <>
                <label htmlFor="method" className="sr-only">
                  Methode
                </label>
                <select
                  id="method"
                  name="method"
                  value={form.method}
                  onChange={set("method")}
                  className="rounded-lg border border-white/15 bg-white/[0.06] px-2 py-1.5 font-mono text-sm font-bold"
                >
                  {METHODS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </>
            )}
            <input
              ref={urlRef}
              id="base_url"
              name="base_url"
              type="url"
              inputMode="url"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              required
              placeholder={URL_EXAMPLE[kind]}
              value={form[urlField]}
              onChange={set(urlField)}
              aria-invalid={urlError ? true : undefined}
              aria-describedby="base_url-hilfe base_url-status"
              className="min-w-0 flex-1 basis-56 bg-transparent py-2 font-mono text-base font-medium caret-cyan placeholder:text-white/45 focus:outline-none"
            />
            {isLlm && (
              <button
                type="button"
                onClick={checkConnection}
                disabled={check.state === "busy"}
                aria-label="Verbindung prüfen"
                className="btn btn-ghost font-mono text-xs"
              >
                {check.state === "busy" ? "prüfe …" : "Prüfen"}
              </button>
            )}
          </div>
        </div>
        <div id="base_url-status" role="status" className="mt-2 min-h-5 font-mono text-xs">
          {isLlm && check.state === "ok" && (
            <span className="text-mint-soft">
              ✓ erreichbar · {check.models[0]?.id ?? "kein Modell gemeldet"}
              {check.models.length > 1 ? ` (+${check.models.length - 1} weitere)` : ""}
            </span>
          )}
          {isLlm && check.state === "fail" && <span className="text-rose-soft">✗ {check.message}</span>}
        </div>
        {urlError && (
          <p role="alert" className="mt-1 text-sm text-rose-soft">
            {urlError}
          </p>
        )}
        <p id="base_url-hilfe" className="sr-only">
          {URL_HELP[kind]}
        </p>
      </div>

      <fieldset>
        <legend className={legend}>Was wird getestet?</legend>
        <div className="flex flex-wrap gap-3">
          {KINDS.map((t) => {
            const on = t.value === kind;
            // Abläufe brauchen den Browser im Backend-Image (Ziel „browser“) – sonst nur anzeigen, nicht wählbar
            const off = t.value === "flow" && !features.flow;
            return (
              <label
                key={t.value}
                className={`flex min-h-[42px] items-center gap-2 rounded-xl border px-4 text-sm ${focusRing} ${
                  off
                    ? "cursor-not-allowed border-dashed border-white/15 bg-white/[0.03] font-medium text-white/60"
                    : on
                      ? "cursor-pointer border-[#a68cff]/70 bg-violet/20 font-semibold shadow-[0_4px_18px_rgb(124_92_255/0.35)]"
                      : "cursor-pointer border-white/15 bg-white/[0.03] font-medium text-white/80 hover:bg-white/[0.07]"
                }`}
              >
                <input
                  type="radio"
                  name="kind"
                  value={t.value}
                  checked={on}
                  disabled={off}
                  aria-describedby={off ? "ablauf-hinweis" : undefined}
                  onChange={() => chooseKind(t.value as RunKind)}
                  className="sr-only"
                />
                <span aria-hidden="true">{t.icon}</span>
                {t.label}
                {off && (
                  <span id="ablauf-hinweis" className="ml-1 font-mono text-[9px] font-bold uppercase tracking-[0.12em] text-amber-soft">
                    braucht Browser-Image
                  </span>
                )}
              </label>
            );
          })}
        </div>
      </fieldset>

      {isFlow && (
        <fieldset>
          <legend className={legend}>Was passiert auf der Seite?</legend>
          <label htmlFor="flow_steps" className="mb-1 block text-xs font-medium text-white/70">
            Die Schritte
          </label>
          <textarea
            id="flow_steps"
            name="flow_steps"
            rows={9}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            placeholder={STEP_EXAMPLE}
            value={form.flow_steps}
            onChange={set("flow_steps")}
            aria-describedby="flow_steps-hilfe"
            className="field font-mono text-[13px] leading-relaxed"
          />
          <p id="flow_steps-hilfe" className="mt-1.5 text-xs text-white/60">
            Ein Schritt je Zeile, so wie ein Mensch es tun würde. Die Startseite oben wird zuerst geöffnet. Ab „messen ab hier“ zeichnet ein
            unsichtbarer Browser auf, was die Seite an den Server schickt – unter Last wird genau das hunderte Male abgespielt. Zugangsdaten
            als {"{platzhalter}"} schreiben, dann erscheinen unten Felder dafür.
          </p>
          {placeholders.length > 0 && (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {placeholders.map((p) => (
                <div key={p}>
                  <label htmlFor={`secret-${p}`} className="mb-1 block text-xs font-medium text-white/70">
                    Wert für {`{${p}}`}
                  </label>
                  <input
                    id={`secret-${p}`}
                    name={`secret-${p}`}
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    value={secrets[p] ?? ""}
                    onChange={(e) => setSecrets((s) => ({ ...s, [p]: e.target.value }))}
                    aria-describedby="secrets-hilfe"
                    className="field font-mono"
                  />
                </div>
              ))}
              <p id="secrets-hilfe" className="text-xs text-white/60 sm:col-span-2">
                Wird nur für diesen Start benutzt – nicht gemerkt, nicht gespeichert, nicht im Bericht.
              </p>
            </div>
          )}
        </fieldset>
      )}

      <fieldset>
        <legend className={legend}>Wie gründlich?</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          {profiles.map((p) => {
            const on = profile === p.key;
            return (
              <label
                key={p.key}
                className={`relative cursor-pointer rounded-2xl border px-5 py-4 ${focusRing} ${
                  on
                    ? "border-[#a68cff]/70 bg-gradient-to-br from-violet/25 to-cyan/5 shadow-[0_8px_30px_rgb(124_92_255/0.3)]"
                    : "border-white/10 bg-white/[0.035]"
                }`}
              >
                <input type="radio" name="profile" value={p.key} checked={on} onChange={() => setProfile(p.key)} className="sr-only" />
                <span className={`block font-display text-lg font-bold ${on ? "" : "text-white/75"}`}>{p.title}</span>
                <span className="mt-1 block text-xs font-medium text-white/70">
                  {minutes(p.values, kind)} · {p.hint}
                </span>
                <span className={`mt-2 block font-mono text-[10px] ${on ? "text-[#ccbfff]" : "text-white/60"}`}>
                  {levelsInfo(p.values.levels)}
                </span>
                <svg aria-hidden="true" width="22" height="22" viewBox="0 0 22 22" className="absolute right-4 top-[18px]">
                  {on ? (
                    <>
                      <circle cx="11" cy="11" r="10.5" fill="#7C5CFF" stroke="#C4B5FD" />
                      <path
                        d="M6.5 11.2l3 3 6-6.1"
                        fill="none"
                        stroke="#fff"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </>
                  ) : (
                    <circle cx="11" cy="11" r="10" fill="none" stroke="#fff" strokeOpacity="0.35" strokeWidth="1.5" />
                  )}
                </svg>
              </label>
            );
          })}
        </div>
      </fieldset>

      <fieldset>
        <legend className={legend}>Was ist euch wichtig?</legend>
        <div className="grid gap-3 sm:grid-cols-3">
          {TARGETS[kind].map((t) => (
            <div key={t.name} className="tile flex flex-col justify-between px-4 pb-2 pt-2.5 focus-within:border-cyan/60">
              <label htmlFor={t.name} className="block text-[11px] font-medium text-white/65">
                {t.label}
              </label>
              <div className="flex items-baseline gap-1.5">
                <input
                  id={t.name}
                  name={t.name}
                  type={t.text ? "text" : "number"}
                  inputMode={t.text ? "text" : "decimal"}
                  min={t.text ? undefined : t.min}
                  step={t.text ? undefined : t.step}
                  maxLength={t.text ? 3 : undefined}
                  autoComplete="off"
                  placeholder={t.placeholder}
                  value={form[t.name]}
                  onChange={set(t.name)}
                  aria-describedby={`${t.name}-einheit`}
                  className="w-16 bg-transparent font-display text-xl font-bold placeholder:text-white/40 focus:outline-none [appearance:textfield]"
                />
                <span id={`${t.name}-einheit`} className="font-display text-[13px] font-bold text-white/60">
                  {t.unit}
                </span>
              </div>
            </div>
          ))}
        </div>
      </fieldset>

      <details className="group rounded-2xl border border-white/10 bg-white/[0.03] open:pb-4">
        <summary id={moreId} className="cursor-pointer list-none rounded-2xl px-5 py-3 text-sm font-medium text-white/75 hover:text-white">
          <span aria-hidden="true" className="mr-2 inline-block transition-transform group-open:rotate-90">
            ›
          </span>
          Weitere Einstellungen
        </summary>
        {isFlow ? (
          <div role="group" aria-labelledby={moreId} className="px-5 pt-1">
            <h3 className="mb-2 text-xs font-medium text-white/70">So schreibt man Schritte</h3>
            <dl className="grid gap-x-4 gap-y-2 text-xs sm:grid-cols-[auto_1fr]">
              {STEP_WORDS.map(([word, meaning]) => (
                <div key={word} className="contents">
                  <dt className="font-mono text-[12px] text-cyan">{word}</dt>
                  <dd className="text-white/70">{meaning}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-xs text-white/60">
              Grenzen: Alle simulierten Nutzer teilen sich die Sitzung der Aufzeichnung (ein Konto). Seiten mit Dauerverbindung
              (WebSocket) im Messbereich lassen sich so nicht abspielen. Veränderliche Werte wie eine Chat-ID erkennt der Test selbst und
              holt sie bei jeder Wiederholung frisch.
            </p>
          </div>
        ) : isApi ? (
          <div role="group" aria-labelledby={moreId} className="grid gap-4 px-5 pt-1">
            <div>
              <label htmlFor="headers_text" className="mb-1 block text-xs font-medium text-white/70">
                Kopfzeilen
              </label>
              <textarea
                id="headers_text"
                name="headers_text"
                rows={3}
                autoComplete="off"
                spellCheck={false}
                placeholder={"Authorization: Bearer …\nX-Mandant: 42"}
                value={form.headers_text}
                onChange={set("headers_text")}
                aria-describedby="headers_text-hilfe"
                className="field font-mono text-[13px]"
              />
              <p id="headers_text-hilfe" className="mt-1 text-xs text-white/60">
                Eine je Zeile als „Name: Wert“. Werden nicht gespeichert und erscheinen nicht im Ergebnis.
              </p>
            </div>
            {writes && (
              <div>
                <label htmlFor="body_text" className="mb-1 block text-xs font-medium text-white/70">
                  Body
                </label>
                <textarea
                  id="body_text"
                  name="body_text"
                  rows={4}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder='{"name": "Beispiel"}'
                  value={form.body_text}
                  onChange={set("body_text")}
                  aria-describedby="body_text-hilfe"
                  className="field font-mono text-[13px]"
                />
                <p id="body_text-hilfe" className="mt-1 text-xs text-white/60">
                  Wird mit jeder Anfrage unverändert gesendet (ohne eigene Kopfzeile als application/json). Wird nicht gespeichert.
                </p>
              </div>
            )}
          </div>
        ) : isWeb ? (
          <div role="group" aria-labelledby={moreId} className="px-5 pt-1">
            <label className="flex cursor-pointer items-start gap-3 text-sm text-white/85">
              <input
                type="checkbox"
                checked={includeAssets}
                onChange={(e) => setIncludeAssets(e.target.checked)}
                className="mt-0.5 size-5 shrink-0 accent-violet"
              />
              <span>
                Auch Bilder, Styles und Skripte der Seite laden
                <span className="mt-0.5 block text-xs text-white/60">
                  Wie ein Browser beim ersten Besuch. Ohne Haken wird nur das HTML geholt – das misst vor allem den Server selbst. Dateien
                  von fremden Servern werden nie angefragt.
                </span>
              </span>
            </label>
          </div>
        ) : (
          <div role="group" aria-labelledby={moreId} className="grid gap-4 px-5 pt-1 sm:grid-cols-2">
            <div>
              <label htmlFor="model" className="mb-1 block text-xs font-medium text-white/70">
                Modell
              </label>
              <input
                id="model"
                name="model"
                list="modelle"
                autoComplete="off"
                spellCheck={false}
                placeholder="automatisch: das erste des Servers"
                value={form.model}
                onChange={set("model")}
                className="field font-mono"
              />
              <datalist id="modelle">{check.state === "ok" && check.models.map((m) => <option key={m.id} value={m.id} />)}</datalist>
            </div>
            <div>
              <label htmlFor="api_key" className="mb-1 block text-xs font-medium text-white/70">
                API-Schlüssel
              </label>
              <input
                id="api_key"
                name="api_key"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={form.api_key}
                onChange={set("api_key")}
                aria-describedby="api_key-hilfe"
                className="field font-mono"
              />
              <p id="api_key-hilfe" className="mt-1 text-xs text-white/60">
                Nur nötig, wenn der Server einen verlangt. Wird nicht gespeichert.
              </p>
            </div>
            <fieldset className="sm:col-span-2">
              <legend className="mb-2 text-xs font-medium text-white/70">
                Kosten – für den Vergleich mit der Cloud (Beispielwerte, bitte anpassen)
              </legend>
              <div className="grid gap-3 sm:grid-cols-3">
                {COST_FIELDS.map((f) => (
                  <div key={f.name}>
                    <label htmlFor={f.name} className="mb-1 block text-xs text-white/70">
                      {f.label} <span className="text-white/55">({f.unit})</span>
                    </label>
                    <input
                      id={f.name}
                      name={f.name}
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="any"
                      value={form[f.name]}
                      onChange={set(f.name)}
                      className="field font-mono"
                    />
                  </div>
                ))}
              </div>
            </fieldset>
          </div>
        )}
      </details>

      <div>
        {writes && (
          <p className="mb-4 rounded-xl border border-rose/45 bg-rose/10 px-4 py-3 text-sm text-rose-soft">
            Jede Anfrage wird wirklich ausgeführt. Mit {form.method} verändert der Test Daten – hunderte Male pro Minute. Nur gegen eine
            Testumgebung richten.
          </p>
        )}
        {!isLlm && (
          <div
            className={`mb-4 rounded-xl border px-4 py-3 ${confirmError ? "border-rose/60 bg-rose/10" : "border-amber/35 bg-amber/[0.07]"}`}
          >
            <label className="flex cursor-pointer items-start gap-3 text-sm text-white/90">
              <input
                ref={confirmRef}
                type="checkbox"
                checked={confirmed}
                onChange={(e) => {
                  setConfirmed(e.target.checked);
                  setConfirmError(false);
                }}
                aria-invalid={confirmError ? true : undefined}
                aria-describedby="bestaetigung-hilfe"
                className="mt-0.5 size-5 shrink-0 accent-violet"
              />
              <span>Das ist unsere eigene {thing} – oder ich habe die Erlaubnis, sie zu testen.</span>
            </label>
            <p id="bestaetigung-hilfe" className="mt-1.5 pl-8 text-xs text-white/65">
              Für fremde {THINGS[kind]} sieht ein Lasttest aus wie ein Angriff und kann strafbar sein. Der Test gibt sich als
              „LAST-Lasttest“ zu erkennen.
            </p>
            {confirmError && (
              <p role="alert" className="mt-1.5 pl-8 text-sm text-rose-soft">
                Bitte erst bestätigen, dass ihr diese {thing} testen dürft.
              </p>
            )}
          </div>
        )}
        {(serverError || formError) && (
          <p role="alert" className="mb-3 rounded-xl border border-rose/45 bg-rose/10 px-4 py-3 text-sm text-rose-soft">
            {serverError ?? formError}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="flex min-h-16 w-full items-center justify-center gap-3.5 rounded-2xl border border-white/25 bg-gradient-to-r from-violet via-[#6180ff] to-cyan font-display text-xl font-bold tracking-[-0.01em] shadow-[0_14px_40px_rgb(124_92_255/0.55),0_0_24px_rgb(34_211_238/0.35)] transition hover:brightness-110 disabled:cursor-wait disabled:opacity-70 [text-shadow:0_1px_2px_rgb(0_0_0/0.45)]"
        >
          {busy ? "Startet …" : "Test starten"}
          <kbd
            aria-hidden="true"
            className="grid h-[26px] w-[30px] place-items-center rounded-[7px] border border-white/35 bg-white/20 font-sans text-[15px] font-normal"
          >
            ↵
          </kbd>
        </button>
        <p className="mt-5 text-xs text-white/60">
          {isLlm ? "Nur gegen eigene Server testen." : `Nur eigene ${THINGS[kind]} testen.`} · Läuft im Hintergrund weiter – du kannst die
          Seite schließen.
        </p>
      </div>
    </form>
  );
}
