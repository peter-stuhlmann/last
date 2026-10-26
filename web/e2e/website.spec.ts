import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Die Test-Website läuft im selben Docker-Netz wie das Backend (Dienst „testsite“).
const SITE = "http://testsite:8000/";

/** Prüft die Seite im echten Browser auf Barrierefreiheit – inklusive Farbkontrast. */
async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  const summary = results.violations.map(
    (v) =>
      `${v.id}: ${v.help} → ${v.nodes
        .map((n) => n.target.join(" "))
        .slice(0, 4)
        .join(" | ")}`,
  );
  expect(summary).toEqual([]);
}

/** Keine Fehler in der Konsole – insbesondere keine Verstöße gegen die Content Security Policy. */
function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  return errors;
}

test("Startseite ist barrierefrei und lädt nichts von fremden Servern", async ({ page, baseURL }) => {
  const errors = collectConsoleErrors(page);
  const foreign: string[] = [];
  page.on("request", (req) => {
    if (!req.url().startsWith(baseURL!)) foreign.push(req.url());
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Wie viel hält");
  await expectAccessible(page);
  await page.locator("label", { hasText: "Website" }).click();
  await expectAccessible(page);
  expect(foreign).toEqual([]);
  expect(errors).toEqual([]);
});

test("Website-Test von der Eingabe bis zum Bericht", async ({ page, request }) => {
  const errors = collectConsoleErrors(page);

  // Damit der Durchlauf Sekunden statt Minuten dauert, wird nur die Dauer der Schritte gekürzt.
  // Formular, Prüfung, Backend und Berichte laufen echt.
  await page.route("**/api/start", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    await route.continue({
      postData: JSON.stringify({
        ...body,
        levels: "1,4",
        level_seconds: 5,
        warmup_seconds: 1,
        min_samples: 3,
        baseline_requests: 2,
        tests: "baseline,ramp",
      }),
    });
  });

  await page.goto("/");
  await page.locator("label", { hasText: "Website" }).click();
  await page.getByRole("textbox", { name: "Adresse der Website" }).fill(SITE);
  await page.getByRole("spinbutton", { name: "Besucher gleichzeitig" }).fill("5");

  // Ohne Bestätigung startet nichts
  await page.getByRole("button", { name: "Test starten" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText("bestätigen");
  await expect(page).toHaveURL(/\/$/);

  await page.getByRole("checkbox", { name: /eigene Website/ }).check();
  await page.getByRole("button", { name: "Test starten" }).click();

  // Live-Ansicht
  await expect(page).toHaveURL(/\/lauf$/);
  await expect(page.getByRole("list", { name: "Schritte des Tests" })).toBeVisible();
  await expect(page.getByText("Besucher gleichzeitig auf der Website")).toBeVisible();
  await expectAccessible(page);

  // Ergebnis
  await page.getByRole("link", { name: /Ergebnis ansehen/ }).click({ timeout: 120_000 });
  await expect(page).toHaveURL(/\/laeufe\/results_/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Licht.");
  await expect(page.getByRole("heading", { name: "Was wurde gemessen?" })).toBeVisible();
  await expect(page.getByText(/und 2 Dateien derselben Website/)).toBeVisible();
  await expectAccessible(page);

  // Berichte sind echte Dateien
  const pptx = await request.get((await page.getByRole("link", { name: /PowerPoint herunterladen/ }).getAttribute("href"))!);
  expect(pptx.status()).toBe(200);
  expect((await pptx.body()).subarray(0, 2).toString()).toBe("PK");
  expect(pptx.headers()["content-disposition"]).toContain("Lasttest-Website_");
  const pdf = await request.get((await page.getByRole("link", { name: /PDF/ }).getAttribute("href"))!);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");

  // Der Lauf steht in der Liste
  await page.goto("/laeufe");
  await expect(page.getByText("Website", { exact: true }).first()).toBeVisible();
  await expectAccessible(page);

  expect(errors).toEqual([]);
});

test("ein laufender Test lässt sich nach Rückfrage abbrechen", async ({ page }) => {
  await page.goto("/");
  await page.locator("label", { hasText: "Website" }).click();
  await page.getByRole("textbox", { name: "Adresse der Website" }).fill(SITE);
  await page.getByRole("checkbox", { name: /eigene Website/ }).check();
  await page.getByRole("button", { name: "Test starten" }).click();
  await expect(page).toHaveURL(/\/lauf$/);

  await page.getByRole("button", { name: "Abbrechen", exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: "Test wirklich abbrechen?" });
  await expect(dialog.getByRole("button", { name: "Weiterlaufen lassen" })).toBeFocused();
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Ja, abbrechen" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Gestoppt" })).toBeVisible({ timeout: 30_000 });
});

test("fremde Seiten können keinen Test starten", async ({ request }) => {
  const body = { kind: "web", base_url: SITE, confirm_owner: true };
  const crossSite = await request.post("/api/start", { data: body, headers: { origin: "https://evil.example" } });
  expect(crossSite.status()).toBe(403);
  const wrongHost = await request.get("/", { headers: { host: "evil.example" } });
  expect(wrongHost.status()).toBe(421);
  const noConfirm = await request.post("/api/start", { data: { kind: "web", base_url: SITE } });
  expect(noConfirm.status()).toBe(400);
});
