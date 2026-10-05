import "server-only";
import { normalizeSummary } from "./events";
import type { ModelInfo, RunInfo, RunState, Summary } from "./types";

// Das Python-Backend ist nur im internen Netz erreichbar; der Browser spricht nie direkt mit ihm.
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://127.0.0.1:8090").replace(/\/+$/, "");

export const BACKEND_DOWN = "Das Test-Backend ist nicht erreichbar.";

export function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${BACKEND_URL}${path}`, { cache: "no-store", ...init });
}

async function backendJson<T>(path: string, timeoutMs = 4000): Promise<T | null> {
  try {
    const res = await backendFetch(path, { signal: AbortSignal.timeout(timeoutMs) });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

export interface Defaults {
  defaults: Record<string, unknown>;
  quick: Record<string, unknown>;
  /** Standardwerte für Website-Tests; fehlt bei einem älteren Backend */
  web?: { defaults: Record<string, unknown>; quick: Record<string, unknown> };
  api?: { defaults: Record<string, unknown>; quick: Record<string, unknown> };
}

export const getDefaults = () => backendJson<Defaults>("/api/defaults");

export async function getRuns(): Promise<RunInfo[] | null> {
  return (await backendJson<{ runs: RunInfo[] }>("/api/runs"))?.runs ?? null;
}

export async function getSummary(name: string): Promise<Summary | null> {
  return normalizeSummary(await backendJson<Summary>(`/api/runs/${name}/summary.json`, 8000));
}

export interface BackendState {
  state: RunState;
  run: string;
  error: string | null;
}

export const getState = () => backendJson<BackendState>("/api/state");

/** Gibt eine Backend-Antwort (Download oder Stream) an den Browser weiter. */
export function passThrough(upstream: Response, extra: Record<string, string> = {}): Response {
  const headers = new Headers({
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    ...extra,
  });
  for (const name of ["content-type", "content-disposition", "content-length"]) {
    const value = upstream.headers.get(name);
    if (value && !headers.has(name)) headers.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}

export function jsonError(error: string, status: number): Response {
  return Response.json({ error }, { status, headers: { "cache-control": "no-store" } });
}

// Groß genug für einen API-Body von 64 kB samt Kopfzeilen
const MAX_BODY = 96 * 1024;

/** Liest einen JSON-Body mit Größenbegrenzung. Gibt bei Fehlern eine fertige Antwort zurück. */
export async function readJson(request: Request): Promise<{ data: unknown } | { response: Response }> {
  const text = await request.text();
  if (text.length > MAX_BODY) return { response: jsonError("Anfrage zu groß.", 413) };
  try {
    return { data: JSON.parse(text) };
  } catch {
    return { response: jsonError("Ungültiges JSON.", 400) };
  }
}

const MAX_MODELS_BYTES = 1024 * 1024;

/** Fragt die Modellliste eines OpenAI-kompatiblen Servers ab. Der Schlüssel geht nur in den Header. */
export async function fetchModels(baseUrl: string, apiKey?: string): Promise<ModelInfo[]> {
  const res = await fetch(`${baseUrl}/models`, {
    headers: apiKey ? { authorization: `Bearer ${apiKey}` } : {},
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const text = await res.text();
  if (text.length > MAX_MODELS_BYTES) throw new Error("Antwort zu groß");
  const data = (JSON.parse(text) as { data?: unknown }).data;
  if (!Array.isArray(data)) return [];
  return data
    .filter((m): m is Record<string, unknown> => typeof m === "object" && m !== null && typeof m.id === "string")
    .slice(0, 200)
    .map((m) => {
      const len = m.max_model_len ?? m.context_length;
      return { id: (m.id as string).slice(0, 200), max_len: typeof len === "number" ? len : null };
    });
}
