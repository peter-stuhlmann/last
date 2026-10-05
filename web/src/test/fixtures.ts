import type { RampStep, RunConfig, Stats, Summary } from "@/lib/types";

export function stats(over: Partial<Stats> = {}): Stats {
  return {
    n: 40,
    ok: 40,
    errors: 0,
    error_rate: 0,
    ttft_p50: 0.3,
    ttft_p95: 0.4,
    user_tps_p50: 50,
    e2e_mean: 5,
    out_tps: 70,
    req_s: 0.2,
    ...over,
  };
}

export function step(concurrency: number, over: Partial<RampStep> = {}): RampStep {
  return { ...stats(), concurrency, fine: false, goodput_pct: 100, ...over };
}

export const config: RunConfig = {
  base_url: "http://spark.buero.lan:8000/v1",
  model: "brain",
  tests: "baseline,ramp,rate,context,spike,soak",
  levels: "1,4,16,32,64",
  level_seconds: 30,
  warmup_seconds: 5,
  baseline_requests: 5,
  rate_seconds: 30,
  context_lengths: "1024,8192,32768",
  context_requests: 2,
  spike_size: 32,
  soak_minutes: 3,
  cooldown: 5,
  think_time: 60,
  target_users: 80,
  slo_ttft: 2,
  slo_user_tps: 10,
  hw_price: 4000,
  server_watts: 200,
  power_price: 0.3,
  cloud_price_in: 0.5,
  cloud_price_out: 1.5,
};

/** Ein abgeschlossener Lauf mit „Grünes Licht“. */
export function finishedSummary(over: Partial<Summary> = {}): Summary {
  return {
    config,
    meta: { started: "2026-10-04T23:41:00", finished: "2026-10-04T23:55:52", current_test: null },
    baseline: stats({ ttft_p50: 0.32, ttft_p95: 0.35, user_tps_p50: 54, out_tps: 54 }),
    ramp: {
      steps: [
        step(1, { out_tps: 72, ttft_p95: 0.32, user_tps_p50: 54 }),
        step(4, { out_tps: 262, ttft_p95: 0.41, user_tps_p50: 40 }),
        step(16, { out_tps: 471, ttft_p95: 0.72, user_tps_p50: 25 }),
        step(32, { out_tps: 612, ttft_p95: 1.4, user_tps_p50: 18 }),
        step(64, { out_tps: 700, ttft_p95: 3.9, user_tps_p50: 9 }),
      ],
      break: null,
      saturated: null,
    },
    rate: {
      stages: [
        { ...stats(), rate: 1, rate_actual: 1, overloaded: false, goodput_pct: 100 },
        { ...stats(), rate: 2, rate_actual: 2, overloaded: false, goodput_pct: 99 },
      ],
      break: null,
      think_time: 60,
    },
    context: {
      steps: [
        { input_len: 1024, single: stats({ ttft_p50: 0.5 }), parallel: null },
        { input_len: 32768, single: stats({ ttft_p50: 8.4 }), parallel: null },
      ],
      limit: null,
      max_ok: 32768,
      server_limit: 32768,
    },
    spike: { size: 32, burst: stats(), recovery: stats(), recovered: true, crashed: false },
    soak: {
      minutes: 3,
      concurrency: 16,
      total: stats(),
      buckets: [],
      degradation: { tps_change_pct: -1, ttft_change_pct: 2 },
    },
    control: { s: stats(), tps_diff_pct: -2, ttft_diff_pct: 1 },
    quality: { overall: "mittel", items: [] },
    capacity: { think_time: 60, rec_concurrency: 32, rate_ok: 2, users: 142, source: "rate" },
    probes: { alone_pct: 100, load_pct: 100, n_alone: 8, n_load: 48, groups: [] },
    economics: {
      own_month: 155,
      cloud_full_month: 4000,
      own_per_1000: 0.41,
      cloud_per_1000: 1.2,
      breakeven_pct: 34,
      hw_price: 4000,
      server_watts: 200,
      power_price: 0.3,
      cloud_price_in: 0.5,
      cloud_price_out: 1.5,
    },
    verdict: {
      status: "good",
      headline: "Der Server ist für unseren Einsatz geeignet.",
      reasons: [["good", "Reicht für etwa 140 aktive Nutzer – gebraucht werden 80."]],
    },
    ...over,
  };
}

function page(over: Partial<Stats> = {}): Stats {
  return { ...stats({ user_tps_p50: null, out_tps: null }), ttft_p50: 0.08, ttft_p95: 0.12, e2e_p50: 0.6, e2e_p95: 0.9, e2e_mean: 0.65, req_s: 10, ...over };
}

/** Ein abgeschlossener Website-Lauf. */
export function webSummary(over: Partial<Summary> = {}): Summary {
  const webStep = (c: number, o: Partial<Stats>): RampStep => ({ ...page(o), concurrency: c, fine: false });
  return {
    config: {
      ...config,
      kind: "web",
      base_url: "https://shop.example/",
      model: null,
      tests: "baseline,ramp,rate,spike,soak",
      think_time: 30,
      target_users: 500,
      slo_load: 3,
    },
    meta: { started: "2026-10-05T10:00:00", finished: "2026-10-05T10:12:00", current_test: null },
    prechecks: { rtt_ms: 80, busy: null, assets: 12, bytes: 48000, total_bytes: 480000, final_url: "https://shop.example/" },
    baseline: page(),
    ramp: {
      steps: [
        webStep(1, { req_s: 1.5, e2e_p95: 0.7 }),
        webStep(16, { req_s: 20, e2e_p95: 1.1 }),
        webStep(32, { req_s: 31, e2e_p95: 2.4, ttft_p95: 0.9 }),
        webStep(64, { req_s: 34, e2e_p95: 6.5, ttft_p95: 3.1 }),
      ],
      break: null,
      saturated: null,
    },
    rate: {
      stages: [{ ...page(), rate: 25, rate_actual: 25, overloaded: false }],
      break: null,
      think_time: 30,
    },
    spike: { size: 32, burst: page(), recovery: page(), recovered: true, crashed: false },
    soak: { minutes: 3, concurrency: 32, total: page(), buckets: [], degradation: { tps_change_pct: 1, ttft_change_pct: 4 } },
    control: { s: page(), tps_diff_pct: -3, ttft_diff_pct: 3 },
    capacity: { think_time: 30, rec_concurrency: 32, rate_ok: 25, users: 766, source: "rate" },
    probes: null,
    economics: null,
    verdict: {
      status: "good",
      headline: "Die Website hält dem Andrang stand.",
      reasons: [["good", "Reicht für ≈ 770 Besucher gleichzeitig – erwartet werden 500."]],
    },
    ...over,
  };
}

/** Ein abgeschlossener HTTP-API-Lauf: gleiche Form wie ein Website-Lauf, andere Bedeutung. */
export function apiSummary(over: Partial<Summary> = {}): Summary {
  const s = webSummary();
  const fast = { ttft_p50: 0.04, ttft_p95: 0.06, e2e_p50: 0.05, e2e_p95: 0.08, e2e_mean: 0.055 };
  const steps = s.ramp!.steps.map((st, i) => ({ ...st, ...fast, e2e_p95: [0.08, 0.2, 0.4, 1.3][i] }));
  return {
    ...s,
    config: {
      ...s.config,
      kind: "api",
      base_url: "https://api.example/v1/items",
      method: "POST",
      expect_status: "201",
      header_names: ["Authorization"],
      body_bytes: 42,
      slo_load: 0.5,
      target_users: 1000,
    },
    prechecks: { rtt_ms: 40, busy: null, status: 200, assets: 0, bytes: 1200, total_bytes: 1200, final_url: "https://api.example/v1/items" },
    baseline: { ...s.baseline!, ...fast },
    ramp: { steps, break: null, saturated: null },
    capacity: { think_time: 30, rec_concurrency: 32, rate_ok: 25, users: 1500, source: "rate" },
    verdict: { status: "good", headline: "Die API hält der Last stand.", reasons: [["good", "Schafft ≈ 1.500 Anfragen pro Minute – erwartet werden 1.000."]] },
    ...over,
  };
}

export const FLOW_STEPS = `öffne https://chat.example/login
tippe in "E-Mail" {email}
tippe in "Passwort" {passwort}
klicke "Anmelden"
warte auf Text "Willkommen"
messen ab hier
tippe in "Nachricht" "Was ist ein Lasttest?"
drücke Enter
warte bis ".antwort" fertig ist (2 s ruhig)`;

/** Ein abgeschlossener Ablauf-Lauf: aufgezeichnet im Browser, abgespielt per HTTP. */
export function flowSummary(over: Partial<Summary> = {}): Summary {
  const s = webSummary();
  const slow = { ttft_p50: 0.9, ttft_p95: 1.2, e2e_p50: 4, e2e_p95: 5.5, e2e_mean: 4.2 };
  const steps = s.ramp!.steps.map((st, i) => ({ ...st, ...slow, req_s: [0.25, 3.5, 6, 6.4][i], e2e_p95: [5.5, 6, 8, 14][i] }));
  const lines = FLOW_STEPS.split("\n");
  return {
    ...s,
    config: {
      ...s.config,
      kind: "flow",
      base_url: "https://chat.example/login",
      steps_text: FLOW_STEPS,
      placeholders: ["email", "passwort"],
      slo_load: 10,
      think_time: 60,
      target_users: 200,
      levels: "1,16,32,64",
    },
    prechecks: {
      rtt_ms: 900, busy: null, status: 200, assets: 2, bytes: 1800, total_bytes: 2000, final_url: "https://chat.example/chat",
      requests: [
        { method: "POST", host: "chat.example", path: "/api/conversations", query: "", status: 201, stream: false, body_bytes: 2, header_names: ["content-type"], dynamic: [] },
        { method: "POST", host: "chat.example", path: "/api/conversations/{{v1}}/messages", query: "", status: 200, stream: true, body_bytes: 32, header_names: ["content-type"], dynamic: ["v1"] },
      ],
      main: 1,
      steps: lines.map((text, i) => ({ line: i + 1, text, screenshot: `schritt_${String(i + 1).padStart(2, "0")}.png`, ms: 300 })),
      measured_ms: 4200,
    },
    baseline: { ...s.baseline!, ...slow, req_s: 0.25 },
    ramp: { steps, break: null, saturated: null },
    rate: { stages: [{ ...s.baseline!, ...slow, rate: 0.5, rate_actual: 0.5, overloaded: false }], break: null, think_time: 60 },
    capacity: { think_time: 60, rec_concurrency: 32, rate_ok: 0.5, users: 32, source: "rate" },
    verdict: { status: "bad", headline: "Die Anwendung schafft die erwartete Nutzerzahl nicht.", reasons: [["bad", "Reicht für ≈ 32 Nutzer gleichzeitig – erwartet werden 200."]] },
    ...over,
  };
}
