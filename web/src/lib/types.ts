// Datenvertrag mit dem Python-Backend (llm_stresstest.py / stresstest_web.py).
// Alle Zeiten in Sekunden, Raten in Anfragen pro Sekunde.

export type TestKey = "baseline" | "ramp" | "rate" | "context" | "spike" | "soak" | "control";
export type Tone = "good" | "warn" | "bad";
export type RunState = "idle" | "running" | "done" | "stopped" | "error";

export type RunKind = "llm" | "web" | "api" | "flow";

export interface RunConfig {
  /** fehlt bei Läufen aus älteren Versionen – dann ist es ein KI-Server-Lauf */
  kind?: RunKind;
  base_url: string;
  model?: string | null;
  tests: string;
  levels: string;
  level_seconds: number;
  warmup_seconds: number;
  baseline_requests: number;
  rate_seconds: number;
  context_lengths: string;
  context_requests: number;
  spike_size: number;
  soak_minutes: number;
  cooldown: number;
  think_time: number;
  target_users: number;
  slo_ttft: number;
  slo_user_tps: number;
  /** Website: Seite geladen / API: Antwort da – nach so vielen Sekunden */
  slo_load?: number;
  /** nur HTTP-API; Kopfzeilen-Werte und Body werden nie gespeichert */
  method?: string;
  expect_status?: string;
  header_names?: string[];
  body_bytes?: number;
  /** nur Ablauf: die Schritte im Wortlaut (Platzhalter bleiben Platzhalter) und ihre Namen */
  steps_text?: string;
  placeholders?: string[];
  hw_price?: number;
  server_watts?: number;
  power_price?: number;
  cloud_price_in?: number;
  cloud_price_out?: number;
  [key: string]: unknown;
}

export interface Stats {
  n: number;
  ok: number;
  errors: number;
  error_rate: number;
  ttft_p50: number | null;
  ttft_p95: number | null;
  user_tps_p50: number | null;
  e2e_mean?: number | null;
  /** Website: Ladezeit der ganzen Seite */
  e2e_p50?: number | null;
  e2e_p95?: number | null;
  out_tps: number | null;
  req_s?: number | null;
  goodput_pct?: number | null;
}

export interface RampStep extends Stats {
  concurrency: number;
  fine: boolean;
}

export interface RateStage extends Stats {
  rate: number;
  rate_actual: number;
  overloaded: boolean;
}

export interface Probes {
  alone_pct: number | null;
  load_pct: number | null;
  n_alone: number;
  n_load: number;
  groups: { n: number; richtig: number }[];
}

export interface Economics {
  own_month: number;
  cloud_full_month: number;
  own_per_1000: number | null;
  cloud_per_1000: number | null;
  breakeven_pct: number | null;
  hw_price: number;
  server_watts: number;
  power_price: number;
  cloud_price_in: number;
  cloud_price_out: number;
}

export interface Summary {
  config: RunConfig;
  meta: {
    started?: string;
    finished?: string;
    current_test?: TestKey | null;
    has_server_metrics?: boolean;
  };
  prechecks?: {
    rtt_ms: number | null;
    busy: number | null;
    assets?: number;
    bytes?: number;
    /** Website: Seite und alle zugehörigen Dateien zusammen */
    total_bytes?: number;
    final_url?: string;
    /** HTTP-API: Status der Antwort ohne Last */
    status?: number;
    /** Ablauf: was der Browser im Messbereich an den Server geschickt hat */
    requests?: RecordedRequest[];
    main?: number;
    steps?: RecordedStep[];
    measured_ms?: number | null;
  };
  baseline?: Stats;
  ramp?: { steps: RampStep[]; break: { concurrency: number; reason: string } | null; saturated: number | null };
  rate?: { stages: RateStage[]; break: { rate: number; reason: string } | null; think_time: number };
  context?: {
    steps: { input_len: number; single: Stats; parallel: Stats | null }[];
    limit: { input_len: number } | null;
    max_ok: number | null;
    server_limit: number | null;
  };
  spike?: { size: number; burst: Stats; recovery: Stats | null; recovered: boolean | null; crashed: boolean };
  soak?: {
    minutes: number;
    concurrency: number;
    total: Stats;
    buckets: unknown[];
    degradation: { tps_change_pct: number | null; ttft_change_pct: number | null } | null;
  };
  control?: { s: Stats; tps_diff_pct: number | null; ttft_diff_pct: number | null };
  skipped?: string[];
  quality?: {
    overall: "hoch" | "mittel" | "niedrig";
    items: { status: Tone | "info"; title: string; value: string; text: string }[];
  };
  capacity: {
    think_time: number;
    rec_concurrency?: number;
    rate_ok?: number;
    users?: number | null;
    source: "rate" | "ramp" | null;
  };
  probes: Probes | null;
  economics: Economics | null;
  verdict: { status: Tone; headline: string; reasons: [Tone, string][] };
  monitor?: Sample[];
}

export interface RecordedRequest {
  method: string;
  host: string;
  path: string;
  query: string;
  status: number;
  stream: boolean;
  body_bytes: number;
  header_names: string[];
  /** Namen der veränderlichen Werte (z. B. v1), die aus einer früheren Antwort kommen */
  dynamic: string[];
}

export interface RecordedStep {
  line: number;
  text: string;
  screenshot: string | null;
  ms: number;
}

export interface Sample {
  t: number;
  phase: string;
  kv?: number;
  running?: number;
  waiting?: number;
}

export type EventMessage =
  | { type: "reset"; run: string }
  | { type: "log"; lines: string[] }
  | { type: "samples"; samples: Sample[] }
  | {
      type: "state";
      state: RunState;
      error: string | null;
      run: string;
      report: boolean;
      pdf: boolean;
      summary: Summary | null;
    };

export interface RunInfo {
  name: string;
  kind?: RunKind;
  model: string | null;
  base_url: string | null;
  started: string | null;
  tests: string[];
  report: boolean;
  pdf: boolean;
}

export interface ModelInfo {
  id: string;
  max_len: number | null;
}
