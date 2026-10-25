/** Runder Achsenschritt (1, 2, 2,5, 3, 5 × 10ⁿ), der mindestens so groß ist wie `raw`. */
export function niceStep(raw: number): number {
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-9)));
  return ([1, 2, 2.5, 3, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
}
