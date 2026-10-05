import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Die Test-Website liefert unter /api.json eine kleine JSON-Antwort – das reicht für einen GET-Test.
const ENDPOINT = "http://testsite:8000/api.json";

test("HTTP-API-Test von der Eingabe bis zum Bericht", async ({ page, request }) => {
  await page.route("**/api/start", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    await route.continue({
      postData: JSON.stringify({ ...body, levels: "1,4", level_seconds: 5, warmup_seconds: 1, min_samples: 3, baseline_requests: 2, tests: "baseline,ramp" }),
    });
  });

  await page.goto("/");
  await page.locator("label", { hasText: "HTTP-API" }).click();
  await expect(page.getByRole("combobox", { name: "Methode" })).toHaveValue("GET");
  await page.getByRole("textbox", { name: "Adresse der API" }).fill(ENDPOINT);
  await page.getByRole("spinbutton", { name: "Anfragen pro Minute" }).fill("600");
  await page.getByText("Weitere Einstellungen").click();
  await page.getByRole("textbox", { name: "Kopfzeilen" }).fill("X-Test: e2e");
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);

  await page.getByRole("checkbox", { name: /eigene API/ }).check();
  await page.getByRole("button", { name: "Test starten" }).click();
  await expect(page).toHaveURL(/\/lauf$/);
  await expect(page.getByText("Anfragen pro Minute, die flüssig durchgehen")).toBeVisible();

  await page.getByRole("link", { name: /Ergebnis ansehen/ }).click({ timeout: 120_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Licht.");
  await expect(page.getByText(/GET \/api\.json/)).toBeVisible();
  await expect(page.getByText(/mit der Kopfzeile X-Test/)).toBeVisible();
  await expect(page.getByText(/Besucher/)).toHaveCount(0);

  const pptx = await request.get((await page.getByRole("link", { name: /PowerPoint herunterladen/ }).getAttribute("href"))!);
  expect(pptx.status()).toBe(200);
  expect(pptx.headers()["content-disposition"]).toContain("Lasttest-API_");

  // Der Wert der Kopfzeile darf nirgends auftauchen
  const summary = await request.get((await page.getByRole("link", { name: /Rohdaten/ }).getAttribute("href"))!.replace("raw_requests.jsonl", "summary.json"));
  expect((await summary.text()).includes('"e2e"')).toBe(false);
});
