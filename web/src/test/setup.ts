import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, expect } from "vitest";

afterEach(() => cleanup());

/** Prüft einen DOM-Ausschnitt mit axe-core und meldet Verstöße lesbar. */
export async function expectAccessible(container: Element) {
  const results = await axe.run(container, {
    // jsdom rechnet kein Layout: Farbkontrast wird im echten Browser geprüft.
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`,
  );
  expect(summary).toEqual([]);
}
