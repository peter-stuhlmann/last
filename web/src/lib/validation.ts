import { z } from "zod";

const MAX_URL = 2048;
export const MAX_STEPS = 20 * 1024;
export const MAX_SECRET = 1024;

/** Seitenschutz (.htaccess = HTTP Basic Auth) beim Ablauf – wie die Platzhalter-Werte nie gemerkt. */
export const siteAuthSchema = z.object({
  user: z
    .string()
    .max(200)
    .regex(/^[^:\x00-\x1f\x7f]*$/, "Seitenschutz: Benutzer ohne Doppelpunkt, eine Zeile"),
  password: z
    .string()
    .max(MAX_SECRET)
    .regex(/^[^\x00-\x1f\x7f]*$/, "Seitenschutz: Passwort in einer Zeile"),
});
export type SiteAuth = z.infer<typeof siteAuthSchema>;
export const MAX_ACCOUNTS = 50;
const PLACEHOLDER = /^[a-zA-Z][a-zA-Z0-9_]{0,31}$/;
const TEST_KEYS = ["baseline", "ramp", "rate", "context", "spike", "soak"];
export const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
export const MAX_API_BODY = 64 * 1024;
// Diese Kopfzeilen setzt der Test selbst oder sie würden die Verbindung manipulieren (wie im Backend)
const FORBIDDEN_HEADERS = [
  "host",
  "content-length",
  "transfer-encoding",
  "connection",
  "upgrade",
  "user-agent",
  "expect",
  "te",
  "trailer",
  "keep-alive",
  "proxy-authorization",
];

const headerSchema = z.object({
  name: z
    .string()
    .trim()
    .regex(/^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$/, "Ungültiger Name einer Kopfzeile")
    .refine((n) => !FORBIDDEN_HEADERS.includes(n.toLowerCase()), "Diese Kopfzeile setzt der Test selbst"),
  // Kein Zeilenumbruch und keine Steuerzeichen – sonst ließen sich weitere Kopfzeilen einschleusen
  value: z
    .string()
    .trim()
    .max(2048)
    .regex(/^[^\x00-\x1f\x7f]*$/, "Ungültiger Wert einer Kopfzeile"),
});

/** „Name: Wert“ je Zeile aus dem Formular → Liste von Kopfzeilen. */
export function parseHeaderLines(textarea: string): { name: string; value: string }[] {
  return textarea
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const i = line.indexOf(":");
      if (i < 1) throw new Error(`Kopfzeile „${line.slice(0, 40)}“: bitte als „Name: Wert“ schreiben.`);
      return { name: line.slice(0, i).trim(), value: line.slice(i + 1).trim() };
    });
}

/** Normalisiert eine Server-Adresse; null, wenn sie nicht zulässig ist. */
/**
 * Ergänzt eine Adresse ohne http:// oder https:// – niemand soll an einem fehlenden Präfix scheitern.
 * Rechner im eigenen Netz (localhost, IP-Adressen, .lan/.local/.home, mit Port) bekommen http://, alles andere https://.
 */
export function withScheme(input: string): string {
  const raw = input.trim();
  if (!raw || /^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) return raw;
  const host = raw.replace(/^\/+/, "").split(/[/?#]/)[0].toLowerCase();
  const name = host.replace(/:\d+$/, "");
  const local =
    host !== name ||
    name === "localhost" ||
    /^\d{1,3}(\.\d{1,3}){3}$/.test(name) ||
    name.startsWith("[") ||
    /\.(lan|local|home|internal|localhost)$/.test(name) ||
    !name.includes(".");
  return `${local ? "http" : "https"}://${raw.replace(/^\/+/, "")}`;
}

export function parseBaseUrl(input: unknown): string | null {
  if (typeof input !== "string") return null;
  const raw = input.trim();
  if (!raw || raw.length > MAX_URL) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  if (url.username || url.password || !url.hostname) return null;
  return raw.replace(/\/+$/, "");
}

const baseUrl = z.string().transform((v, ctx) => {
  const url = parseBaseUrl(v);
  if (!url) {
    ctx.addIssue({ code: "custom", message: "Server-Adresse muss mit http:// oder https:// beginnen." });
    return z.NEVER;
  }
  return url;
});

/** Kommagetrennte ganze Zahlen, z. B. Stufen oder Textlängen. */
function intList(maxValue: number, maxItems: number) {
  return z
    .string()
    .max(200)
    .regex(/^\d{1,7}(,\d{1,7})*$/, "Zahlen mit Komma trennen")
    .refine((v) => {
      const parts = v.split(",").map(Number);
      return parts.length <= maxItems && parts.every((n) => n >= 1 && n <= maxValue);
    }, "Wert außerhalb der Grenzen");
}

const num = (min: number, max: number) => z.coerce.number().min(min).max(max);
const int = (min: number, max: number) => z.coerce.number().int().min(min).max(max);

/**
 * Erlaubte Felder für POST /api/start. Unbekannte Felder werden verworfen –
 * insbesondere alles, was im Backend Pfade steuert (out, report_only, compare).
 */
export const startSchema = z
  .object({
    kind: z.enum(["llm", "web", "api", "flow"]).optional(),
    base_url: baseUrl,
    model: z.string().trim().max(200).optional(),
    api_key: z.string().max(512).optional(),
    tests: z
      .string()
      .max(100)
      .refine((v) => v.split(",").every((t) => TEST_KEYS.includes(t)), "Unbekannter Test")
      .optional(),
    disable_thinking: z.boolean().optional(),
    // Profil (Schnell / Gründlich)
    levels: intList(1024, 16).optional(),
    // Website
    slo_load: num(0.1, 120).optional(),
    include_assets: z.boolean().optional(),
    confirm_owner: z.boolean().optional(),
    // HTTP-API
    method: z.enum(METHODS).optional(),
    headers: z.array(headerSchema).max(20).optional(),
    body: z.string().max(MAX_API_BODY).optional(),
    expect_status: z
      .string()
      .trim()
      .toLowerCase()
      .regex(/^([1-5]xx|[1-5]\d\d)$/, "Erwarteter Status: z. B. 2xx oder 201")
      .optional(),
    // Ablauf: Schritte im Wortlaut; die Werte der Platzhalter gehen nur ans Backend, nie in eine Datei
    steps: z.string().max(MAX_STEPS).optional(),
    secrets: z
      .record(z.string().regex(PLACEHOLDER, "Platzhalter: Buchstaben, Ziffern, Unterstrich"), z.string().max(MAX_SECRET))
      .refine((r) => Object.keys(r).length <= 20, "Höchstens 20 Platzhalter")
      .optional(),
    // mehrere Konten: eine Werte-Zuordnung je Konto; kommen unter Last reihum dran
    site_auth: siteAuthSchema.optional(),
    accounts: z
      .array(
        z
          .record(z.string().regex(PLACEHOLDER, "Platzhalter: Buchstaben, Ziffern, Unterstrich"), z.string().max(MAX_SECRET))
          .refine((r) => Object.keys(r).length <= 20, "Höchstens 20 Platzhalter"),
      )
      .min(1, "Mindestens ein Konto")
      .max(MAX_ACCOUNTS, `Höchstens ${MAX_ACCOUNTS} Konten`)
      .optional(),
    level_seconds: int(5, 600).optional(),
    warmup_seconds: int(0, 120).optional(),
    min_samples: int(1, 1000).optional(),
    fine_steps: int(0, 5).optional(),
    context_lengths: intList(2_000_000, 12).optional(),
    context_requests: int(1, 20).optional(),
    spike_size: int(1, 1024).optional(),
    soak_minutes: num(0.5, 240).optional(),
    soak_bucket: int(5, 600).optional(),
    baseline_requests: int(1, 100).optional(),
    rate_seconds: int(5, 600).optional(),
    probe_count: int(0, 100).optional(),
    // Ziele
    target_users: int(0, 1_000_000).optional(),
    slo_ttft: num(0.05, 600).optional(),
    slo_user_tps: num(0.1, 10_000).optional(),
    think_time: num(1, 3600).optional(),
    // Kosten
    hw_price: num(0, 10_000_000).optional(),
    amort_months: int(1, 240).optional(),
    server_watts: num(0, 100_000).optional(),
    power_price: num(0, 100).optional(),
    cloud_price_in: num(0, 10_000).optional(),
    cloud_price_out: num(0, 10_000).optional(),
  })
  // Ein Lasttest sieht für fremde Server, Websites und APIs aus wie ein Angriff – ohne Bestätigung kein Start.
  .refine((v) => v.confirm_owner === true, {
    path: ["confirm_owner"],
    message: "Bitte bestätigen, dass ihr diesen Server, diese Website oder API testen dürft.",
  })
  .refine((v) => v.kind !== "flow" || (v.steps ?? "").trim().length > 0, {
    path: ["steps"],
    message: "Ein Ablauf braucht mindestens einen Schritt.",
  });

export type StartPayload = z.infer<typeof startSchema>;

export const MAX_TITLE = 80;
export const MAX_NOTE = 2000;
export const MAX_TAGS = 10;
export const TAG_RE = /^[a-z0-9äöüß][a-z0-9äöüß._-]{0,23}$/;

/** Titel, Tags, Notiz, Pin eines Laufs – dieselben Grenzen wie im Backend (clean_notes). */
export const notesSchema = z.object({
  title: z
    .string()
    .trim()
    .max(MAX_TITLE, `Titel: höchstens ${MAX_TITLE} Zeichen`)
    .regex(/^[^\x00-\x1f\x7f]*$/, "Titel: eine Zeile")
    .nullable()
    .optional(),
  tags: z
    .array(z.string().trim().toLowerCase().regex(TAG_RE, "Tag: bis 24 Zeichen aus Buchstaben, Ziffern, Punkt, Strich"))
    .max(MAX_TAGS, `Höchstens ${MAX_TAGS} Tags`)
    .transform((tags) => [...new Set(tags)])
    .optional(),
  note: z.string().max(MAX_NOTE, `Notiz: höchstens ${MAX_NOTE} Zeichen`).optional(),
  pinned: z.boolean().optional(),
});

export type NotesPayload = z.infer<typeof notesSchema>;

const secretsSchema = z
  .record(z.string().regex(PLACEHOLDER, "Platzhalter: Buchstaben, Ziffern, Unterstrich"), z.string().max(MAX_SECRET))
  .refine((r) => Object.keys(r).length <= 20, "Höchstens 20 Platzhalter");

// Ein Ziel darf keine Anführungszeichen enthalten – sie beenden es in der Schritt-Sprache
const targetText = z
  .string()
  .trim()
  .min(1)
  .max(200)
  .regex(/^[^"\x00-\x1f]*$/, "Ungültiges Ziel");

export const LIVE_KEYS = ["Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Space", "Backspace"] as const;

/** Vorführen, POST /api/flow/live/start: ein angefangener Ablauf (beginnt mit „öffne“) und die Werte seiner Platzhalter. */
export const liveStartSchema = z.object({
  steps: z
    .string()
    .max(MAX_STEPS)
    .refine((v) => /^\s*öffne\s+https?:\/\//i.test(v), "Der Ablauf muss mit „öffne https://…“ beginnen."),
  secrets: secretsSchema.optional(),
  site_auth: siteAuthSchema.optional(),
  /** Live-Vorführen: die Seite als Videostrom, Eingaben direkt in den Browser */
  stream: z.boolean().optional(),
});

const coord = (max: number) => z.number().min(0).max(max);
const oneLine = z
  .string()
  .min(1)
  .max(4000)
  .regex(/^[^\n\r]*$/, "Der Text muss eine Zeile sein");

/** Live-Vorführen, POST /api/flow/live/input: Maus, Rad, Tasten und Text – in der Reihenfolge, in der der Nutzer sie ausgelöst hat. */
export const liveInputSchema = z.object({
  session: z.string().regex(/^[0-9a-f]{32}$/, "Unbekannte Sitzung"),
  measuring: z.boolean().optional(),
  events: z
    .array(
      z.discriminatedUnion("t", [
        z.object({ t: z.literal("move"), x: coord(1280), y: coord(800) }),
        z.object({ t: z.literal("click"), x: coord(1280), y: coord(800), dbl: z.boolean().optional() }),
        z.object({
          t: z.literal("wheel"),
          x: coord(1280),
          y: coord(800),
          dx: z.number().min(-5000).max(5000).optional(),
          dy: z.number().min(-5000).max(5000).optional(),
        }),
        z.object({ t: z.literal("type"), text: oneLine }),
        z.object({ t: z.literal("text"), text: oneLine }),
        z.object({
          t: z.literal("key"),
          key: z.string().regex(/^(?:[A-Za-z0-9]{1,12}|.)$/, "Ungültige Taste"),
          mods: z
            .array(z.enum(["Control", "Shift", "Alt", "Meta"]))
            .max(3)
            .optional(),
        }),
      ]),
    )
    .min(1)
    .max(60),
});

/** Vorführen, POST /api/flow/live/look: nur ein frisches Bild der Seite. */
export const liveLookSchema = z.object({ session: z.string().regex(/^[0-9a-f]{32}$/, "Unbekannte Sitzung") });

/** Vorführen, POST /api/flow/live/act: ein Klick auf ein Element, eine Eingabe oder eine Taste. */
export const liveActSchema = z.object({
  session: z.string().regex(/^[0-9a-f]{32}$/, "Unbekannte Sitzung"),
  secrets: secretsSchema.optional(),
  action: z.discriminatedUnion("type", [
    z.object({ type: z.literal("pick"), mark: z.string().regex(/^\d{1,7}$/), measuring: z.boolean().optional() }),
    // Klick auf eine Stelle des Bildes, wo kein Knopf erkannt wurde (z. B. ein Schalter aus einem <div>)
    z.object({
      type: z.literal("pick_at"),
      x: z.number().min(0).max(1280),
      y: z.number().min(0).max(800),
      measuring: z.boolean().optional(),
    }),
    z.object({ type: z.literal("press"), key: z.enum(LIVE_KEYS), measuring: z.boolean().optional() }),
    // Blättern an einer Stelle der Seite (Koordinaten im Browserfenster 1280×800) – kein Schritt im Ablauf
    z.object({
      type: z.literal("scroll"),
      x: z.number().min(0).max(1280),
      y: z.number().min(0).max(800),
      dy: z.number().min(-5000).max(5000),
    }),
    z.object({
      type: z.literal("fill"),
      target: z.object({ target: targetText, near: targetText.optional(), nth: z.number().int().min(1).max(999).optional() }),
      text: z
        .string()
        .max(4000)
        .regex(/^[^\n\r]*$/, "Der Text muss eine Zeile sein"),
      enter: z.boolean().optional(),
      measuring: z.boolean().optional(),
    }),
  ]),
});

export const modelsRequestSchema = z.object({
  base_url: baseUrl,
  api_key: z.string().max(512).optional(),
});

/** Erste verständliche Fehlermeldung aus einem Zod-Fehler. */
export function firstIssue(error: z.ZodError): string {
  const issue = error.issues[0];
  return issue ? `${issue.path.join(".") || "Eingabe"}: ${issue.message}` : "Ungültige Eingabe";
}
