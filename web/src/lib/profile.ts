// Rückfallwerte, falls das Backend beim Laden der Startseite nicht antwortet.
// Entsprechen QUICK_PROFILE und den Standardwerten in llm_stresstest.py.
export const FALLBACK_QUICK = {
  levels: "1,4,16,32,64",
  level_seconds: 30,
  warmup_seconds: 5,
  min_samples: 20,
  fine_steps: 1,
  context_lengths: "1024,8192,32768",
  context_requests: 2,
  spike_size: 32,
  soak_minutes: 3,
  soak_bucket: 20,
  baseline_requests: 5,
  rate_seconds: 30,
  probe_count: 8,
};

export const FALLBACK_DEFAULTS = {
  base_url: "http://localhost:8000/v1",
  levels: "1,2,4,8,16,32,64,128,256",
  level_seconds: 60,
  warmup_seconds: 10,
  min_samples: 40,
  fine_steps: 2,
  context_lengths: "512,2048,8192,16384,32768,65536,131072",
  context_requests: 3,
  spike_size: 64,
  soak_minutes: 15,
  soak_bucket: 60,
  baseline_requests: 10,
  rate_seconds: 60,
  probe_count: 12,
  target_users: 0,
  slo_ttft: 2,
  slo_user_tps: 10,
  hw_price: 4000,
  server_watts: 200,
  power_price: 0.3,
  cloud_price_in: 0.5,
  cloud_price_out: 1.5,
};

// Website-Tests: entspricht DEFAULTS und QUICK_PROFILE in web_stresstest.py.
export const FALLBACK_WEB = {
  defaults: {
    tests: "baseline,ramp,rate,spike,soak",
    levels: "1,2,4,8,16,32,64,128,256",
    level_seconds: 60,
    warmup_seconds: 10,
    min_samples: 40,
    baseline_requests: 10,
    rate_seconds: 60,
    spike_size: 64,
    soak_minutes: 15,
    think_time: 30,
    slo_load: 3,
  },
  quick: {
    levels: "1,4,16,32,64",
    level_seconds: 30,
    warmup_seconds: 5,
    min_samples: 20,
    baseline_requests: 5,
    rate_seconds: 30,
    spike_size: 32,
    soak_minutes: 3,
  },
};

// HTTP-API-Tests: wie Websites, aber eine einzelne Anfrage; Ziel 0,5 s Antwortzeit.
export const FALLBACK_API = {
  defaults: { ...FALLBACK_WEB.defaults, slo_load: 0.5 },
  quick: FALLBACK_WEB.quick,
};
