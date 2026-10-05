import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectAccessible } from "@/test/setup";
import { Nutzerstrom } from "./Nutzerstrom";
import { LINES } from "./nutzerstrom-data";

const pause = vi.fn();
const unpause = vi.fn();
let observerCallback: (entries: { isIntersecting: boolean }[]) => void = () => {};

function setup(reducedMotion: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reducedMotion && query.includes("reduce"),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(cb: typeof observerCallback) {
        observerCallback = cb;
      }
      observe() {}
      disconnect() {}
    },
  );
  // jsdom kennt die SMIL-Steuerung nicht
  Object.assign(SVGSVGElement.prototype, { pauseAnimations: pause, unpauseAnimations: unpause });
  return render(<Nutzerstrom />);
}

beforeEach(() => {
  pause.mockReset();
  unpause.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("Nutzerstrom", () => {
  it("ist rein dekorativ und schickt je Linie eine Anfrage zum Server", async () => {
    const { container } = setup(false);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelectorAll("[data-paket]")).toHaveLength(LINES.length);
    expect(container.querySelectorAll("animate, animateTransform").length).toBeGreaterThan(LINES.length);
    // Strenge CSP: keine style-Attribute
    expect(container.querySelector("[style]")).toBeNull();
    await expectAccessible(container);
  });

  it("steht still, wenn weniger Bewegung gewünscht ist", () => {
    setup(true);
    expect(pause).toHaveBeenCalled();
    observerCallback([{ isIntersecting: true }]);
    expect(unpause).not.toHaveBeenCalled();
  });

  it("pausiert außerhalb des sichtbaren Bereichs und läuft danach weiter", () => {
    setup(false);
    expect(pause).not.toHaveBeenCalled();
    observerCallback([{ isIntersecting: false }]);
    expect(pause).toHaveBeenCalledOnce();
    observerCallback([{ isIntersecting: true }]);
    expect(unpause).toHaveBeenCalledOnce();
  });
});
