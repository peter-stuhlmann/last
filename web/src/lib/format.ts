const DASH = "–";

type Num = number | null | undefined;

function isNum(v: Num): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Zahl mit deutscher Schreibweise und fester Nachkommazahl. */
export function nf(v: Num, digits = 1): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function secDigits(v: number): number {
  return v < 1 ? 2 : v < 10 ? 1 : 0;
}

export function splitSecs(v: Num): { value: string; unit: string } {
  return { value: isNum(v) ? nf(v, secDigits(v)) : DASH, unit: "s" };
}

export function secs(v: Num): string {
  return isNum(v) ? `${nf(v, secDigits(v))} s` : DASH;
}

export function eur(v: Num, digits = 0): string {
  return isNum(v) ? `${nf(v, digits)} €` : DASH;
}

export function signedPct(v: Num): string {
  if (!isNum(v)) return DASH;
  const r = Math.round(v);
  const sign = r > 0 ? "+" : r < 0 ? "−" : "±";
  return `${sign}${Math.abs(r)} %`;
}

/** Anfragen pro Sekunde → Fragen pro Minute. */
export function perMinute(ratePerSecond: Num): string {
  if (!isNum(ratePerSecond)) return DASH;
  const m = ratePerSecond * 60;
  return nf(m, m >= 10 ? 0 : 1);
}

/** Rundet Nutzerzahlen wie der PowerPoint-Bericht (round_users). */
export function approxUsers(v: Num): number | null {
  if (!isNum(v) || v <= 0) return null;
  const stepSize = v >= 1000 ? 100 : v >= 100 ? 10 : v >= 30 ? 5 : 1;
  return Math.round(v / stepSize) * stepSize;
}

/** Sekunden als M:SS. */
export function clock(seconds: Num): string {
  if (!isNum(seconds)) return DASH;
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function hostLabel(baseUrl: string | null | undefined): string {
  if (!baseUrl) return DASH;
  try {
    return new URL(baseUrl).host || baseUrl;
  } catch {
    return baseUrl;
  }
}

/** results_20261004_234100 → 04.10.2026, 23:41 */
export function runLabel(name: string): string {
  const m = /^results_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d{2}$/.exec(name);
  return m ? `${m[3]}.${m[2]}.${m[1]}, ${m[4]}:${m[5]}` : name;
}
