import { z } from "zod";

const MAX_URL = 2048;
const TEST_KEYS = ["baseline", "ramp", "rate", "context", "spike", "soak"];

/** Normalisiert eine Server-Adresse; null, wenn sie nicht zulässig ist. */
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
    kind: z.enum(["llm", "web"]).optional(),
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
  // Ein Lasttest sieht für fremde Websites aus wie ein Angriff – ohne Bestätigung kein Start.
  .refine((v) => v.kind !== "web" || v.confirm_owner === true, {
    path: ["confirm_owner"],
    message: "Bitte bestätigen, dass ihr diese Website testen dürft.",
  });

export type StartPayload = z.infer<typeof startSchema>;

export const modelsRequestSchema = z.object({
  base_url: baseUrl,
  api_key: z.string().max(512).optional(),
});

/** Erste verständliche Fehlermeldung aus einem Zod-Fehler. */
export function firstIssue(error: z.ZodError): string {
  const issue = error.issues[0];
  return issue ? `${issue.path.join(".") || "Eingabe"}: ${issue.message}` : "Ungültige Eingabe";
}
