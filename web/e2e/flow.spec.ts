import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Die Test-Anwendung (e2e/testsite/server.py) hat eine Anmeldung und einen Chat, der seine Antwort streamt.
const START = "http://testsite:8000/login";
const STEPS = `tippe in "E-Mail" {email}
tippe in "Passwort" {passwort}
klicke "Anmelden"
warte auf Text "Willkommen"
messen ab hier
tippe in "Nachricht" "Was ist ein Lasttest?"
drücke Enter
warte auf erste Antwort in ".antwort"
warte bis ".antwort" fertig ist (1 s ruhig)`;

test("Ablauf-Test: aufzeichnen, abspielen, Bericht mit Bildschirmfotos", async ({ page, request }) => {
  await page.route("**/api/start", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    await route.continue({
      postData: JSON.stringify({ ...body, levels: "1,2", level_seconds: 5, warmup_seconds: 1, min_samples: 2, baseline_requests: 2, tests: "baseline,ramp" }),
    });
  });

  await page.goto("/");
  await page.locator("label", { hasText: "Ablauf" }).click();
  await page.getByRole("textbox", { name: "Adresse der Startseite" }).fill(START);
  await page.getByRole("textbox", { name: "Die Schritte" }).fill(STEPS);
  await page.getByLabel("Wert für {email}").fill("tester@example.de");
  await page.getByLabel("Wert für {passwort}").fill("sehr-geheim-42");
  await page.getByRole("spinbutton", { name: "Nutzer gleichzeitig" }).fill("20");
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);

  await page.getByRole("checkbox", { name: /eigene Anwendung/ }).check();
  await page.getByRole("button", { name: "Test starten" }).click();
  await expect(page).toHaveURL(/\/lauf$/);
  await expect(page.getByText("Nutzer gleichzeitig in der Anwendung")).toBeVisible();

  await page.getByRole("link", { name: /Ergebnis ansehen/ }).click({ timeout: 150_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Licht.");
  await expect(page.getByText("ab hier wird gemessen")).toBeVisible();
  await expect(page.getByText(/POST \/api\/conversations\/\{v1\}\/messages/)).toBeVisible();
  await expect(page.getByText("gestreamt")).toBeVisible();
  await expect(page.getByText(/Besucher/)).toHaveCount(0);

  // Die Bildschirmfotos kommen wirklich an
  const shot = page.getByRole("img", { name: /Bildschirmfoto nach Zeile 7/ });
  await expect(shot).toBeVisible();
  const png = await request.get((await shot.getAttribute("src"))!);
  expect(png.status()).toBe(200);
  expect(png.headers()["content-type"]).toContain("image/png");
  expect((await request.get((await shot.getAttribute("src"))!.replace("schritt_07.png", "schritt_7.png"))).status()).toBe(404);

  const pptx = await request.get((await page.getByRole("link", { name: /PowerPoint herunterladen/ }).getAttribute("href"))!);
  expect(pptx.status()).toBe(200);
  expect(pptx.headers()["content-disposition"]).toContain("Lasttest-Ablauf_");

  // Weder Zugangsdaten noch das Sitzungs-Cookie dürfen irgendwo stehen
  const rawHref = (await page.getByRole("link", { name: /Rohdaten/ }).getAttribute("href"))!;
  for (const file of ["summary.json", "raw_requests.jsonl"]) {
    const text = await (await request.get(rawHref.replace("raw_requests.jsonl", file))).text();
    expect(text.includes("sehr-geheim-42")).toBe(false);
    expect(text.includes("sitzung-abcdefgh")).toBe(false);
    expect(text.includes("tester@example.de")).toBe(false);
  }
});
