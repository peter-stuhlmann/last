import { describe, expect, it } from "vitest";
import { niceStep } from "./scale";

describe("niceStep", () => {
  it("rundet auf 1, 2, 2,5, 3 oder 5 mal eine Zehnerpotenz auf", () => {
    expect(niceStep(1797)).toBe(2000);
    expect(niceStep(1347)).toBe(2000);
    expect(niceStep(2400)).toBe(2500);
    expect(niceStep(0.37)).toBeCloseTo(0.5);
    expect(niceStep(6)).toBe(10);
  });
});
