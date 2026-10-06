import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Läuft nach api.spec und flow.spec (alphabetisch) – es gibt also schon mindestens zwei Läufe.
test("Läufe verwalten: Titel, Tag, Suche, Verlauf, Papierkorb", async ({ page, request }) => {
  await page.goto("/laeufe");
  const rows = page.getByRole("listitem").filter({ has: page.getByRole("checkbox") });
  const before = await rows.count();
  expect(before).toBeGreaterThanOrEqual(2);

  // Ergebnisseite: Titel, Notiz und Tag setzen
  await rows.first().getByRole("link").first().click();
  await expect(page).toHaveURL(/\/laeufe\/results_/);
  const name = /\/laeufe\/(results_[\w-]+)/.exec(page.url())![1];
  const title = `E2E-Referenz ${Date.now()}`;                           // eindeutig, auch bei wiederholten Läufen
  await page.getByRole("button", { name: "Titel und Notiz bearbeiten" }).click();
  await page.getByLabel("Titel").fill(title);
  await page.getByLabel("Notiz").fill("Vom Durchlauf-Test angelegt.");
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Gespeichert" })).toBeVisible();
  await page.getByLabel("Tag hinzufügen").fill("e2e");
  await page.keyboard.press("Enter");
  await expect(page.getByText("#e2e")).toBeVisible();
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);

  // Notizen liegen neben der Messung, nicht darin
  const notes = await request.get(`/api/runs/${name}/notes`);
  expect(notes.status()).toBe(405);                                    // nur PUT – kein Lesen über eine eigene Route
  const summary = await (await request.get(`/api/runs/${name}/summary.json`)).text();
  expect(summary.includes(title)).toBe(false);

  // Liste: Titel sichtbar, Suche nach Tag
  await page.goto("/laeufe");
  await expect(rows.filter({ hasText: title })).toHaveCount(1);     // der Verlauf oben verlinkt ihn ggf. auch
  await page.getByRole("searchbox", { name: "Läufe durchsuchen" }).fill(title);
  await expect(rows).toHaveCount(1);
  await page.getByRole("searchbox", { name: "Läufe durchsuchen" }).fill("");

  // Löschen mit Rückfrage → Papierkorb-Hinweis, Lauf weg
  await page.getByRole("button", { name: `Lauf ${title} löschen` }).click();
  await expect(page.getByRole("alertdialog")).toContainText("Papierkorb");
  await page.getByRole("button", { name: "In den Papierkorb" }).click();
  await expect(page.getByRole("status").filter({ hasText: "liegt im Papierkorb" })).toBeVisible();
  await expect(rows.filter({ hasText: title })).toHaveCount(0);
  expect((await request.get(`/api/runs/${name}/summary.json`)).status()).toBe(404);
  // Verweise mit Pfadtricks werden nicht einmal weitergereicht
  expect((await request.delete("/api/runs/..%2Fresults", { headers: { "content-type": "application/json" }, data: {} })).status()).toBe(404);
});
