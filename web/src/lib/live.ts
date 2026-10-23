// Antworten des Backends beim Vorführen prüfen, bevor sie in den Browser gehen: nur erwartete Felder,
// Bilder nur als JPEG. Reine Funktionen, damit testbar.
import type { LiveElement, LiveReply, LiveSnapshot, LiveTarget } from "./types";

const KINDS = new Set(["field", "button", "link", "check"]);
const JPEG = "data:image/jpeg;base64,";

const str = (v: unknown, max: number) => (typeof v === "string" ? v.slice(0, max) : "");
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const obj = (v: unknown) => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const jpeg = (v: unknown, max: number) => {
  const s = str(v, max);
  return s.startsWith(JPEG) ? s : null;
};

function cleanSnapshot(v: unknown): LiveSnapshot | undefined {
  const d = obj(v);
  if (!d) return undefined;
  const vp = obj(d.viewport) ?? {};
  const elements = (Array.isArray(d.elements) ? d.elements : [])
    .map(obj)
    .filter((e): e is Record<string, unknown> => !!e && KINDS.has(String(e.kind)) && /^\d{1,7}$/.test(String(e.mark)))
    .slice(0, 200)
    .map((e): LiveElement => {
      const b = obj(e.box) ?? {};
      return { mark: String(e.mark), kind: e.kind as LiveElement["kind"], label: str(e.label, 200), box: { x: num(b.x), y: num(b.y), w: num(b.w), h: num(b.h) } };
    });
  return {
    url: str(d.url, 2048),
    title: str(d.title, 200),
    viewport: { w: num(vp.w) || 1280, h: num(vp.h) || 800 },
    screenshot: jpeg(d.screenshot, 4_000_000),
    elements,
  };
}

function cleanTarget(v: unknown): LiveTarget | undefined {
  const t = obj(v);
  if (!t || (t.kind !== "fill" && t.kind !== "click") || !str(t.target, 200)) return undefined;
  return {
    kind: t.kind,
    target: str(t.target, 200),
    ...(str(t.near, 200) ? { near: str(t.near, 200) } : {}),
    ...(num(t.nth) >= 1 ? { nth: Math.floor(num(t.nth)) } : {}),
    label: str(t.label, 200),
    secret: t.secret === "email" || t.secret === "passwort" ? t.secret : null,
  };
}

export function cleanLiveReply(v: unknown): LiveReply {
  const d = obj(v) ?? {};
  const out: LiveReply = {};
  if (typeof d.session === "string" && /^[0-9a-f]{32}$/.test(d.session)) out.session = d.session;
  const snap = cleanSnapshot(d.snapshot);
  if (snap) out.snapshot = snap;
  if (Array.isArray(d.steps)) out.steps = d.steps.map((s) => str(s, 4500)).filter(Boolean).slice(0, 10);
  if (d.thumb !== undefined) out.thumb = jpeg(d.thumb, 500_000);
  if (d.need === "text") {
    const target = cleanTarget(d.target);
    if (target) Object.assign(out, { need: "text", target });
  }
  if (typeof d.steps_done === "number") out.steps_done = num(d.steps_done);
  const err = obj(d.error);
  if (typeof d.error === "string") out.error = d.error.slice(0, 500);
  else if (err) out.error = { index: num(err.index), message: str(err.message, 500) };
  return out;
}
