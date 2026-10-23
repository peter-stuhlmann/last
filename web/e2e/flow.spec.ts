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
  await page.getByRole("button", { name: "Als Text" }).click();
  await page.getByRole("textbox", { name: "Die Schritte" }).fill(STEPS);
  // Zwei Konten: beide werden aufgezeichnet und kommen unter Last reihum dran
  await page.getByRole("checkbox", { name: /Mehrere Konten/ }).check();
  await page
    .getByRole("textbox", { name: "Konten" })
    .fill(["email, passwort", "tester@example.de, sehr-geheim-42", "zweite@example.de, auch-geheim-43"].join("\n"));
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
  await expect(page.getByText(/reihum auf 2 Konten/)).toBeVisible();
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
    for (const secret of ["sehr-geheim-42", "sitzung-abcdefgh", "tester@example.de", "auch-geheim-43", "sitzung-zweitesk", "zweite@example.de"]) {
      expect(text.includes(secret)).toBe(false);
    }
  }
});

test("Ablauf vorführen: durchklicken, daraus testen", async ({ page }) => {
  await page.route("**/api/start", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    await route.continue({
      postData: JSON.stringify({ ...body, levels: "1,2", level_seconds: 5, warmup_seconds: 1, min_samples: 2, baseline_requests: 2, tests: "baseline,ramp" }),
    });
  });
  await page.goto("/");
  await page.locator("label", { hasText: "Ablauf" }).click();
  await page.getByRole("textbox", { name: "Adresse der Startseite" }).fill(START);
  await page.getByRole("button", { name: /Ablauf vorführen/ }).click();
  const dialog = page.getByRole("dialog", { name: "Ablauf vorführen" });

  // Anmelden – wie ein Mensch: ins Feld klicken, Text eingeben, auf den Knopf klicken
  const type = async (field: string, value: string, enter = false) => {
    await dialog.getByRole("button", { name: `Eingeben in „${field}“` }).click({ timeout: 60_000 });
    // direkt im Feld auf dem Bild: Enter schickt ab, Tab übernimmt nur
    const input = dialog.getByLabel(`Was soll in „${field}“ hinein?`);
    await input.fill(value);
    await input.press(enter ? "Enter" : "Tab");
  };
  await type("E-Mail", "tester@example.de");
  await type("Passwort", "sehr-geheim-42");
  await dialog.getByRole("button", { name: "Klicken auf „Anmelden“" }).click({ timeout: 60_000 });

  // Auf der Chat-Seite: ab hier messen, eine Frage stellen
  await expect(dialog.getByRole("button", { name: "Eingeben in „Nachricht“" })).toBeVisible({ timeout: 60_000 });
  await dialog.getByRole("button", { name: "⏱ Ab hier messen" }).click();
  await type("Nachricht", "Was ist ein Lasttest?", true);
  await expect(dialog.getByRole("complementary", { name: "Der Ablauf bisher" }).getByText("Warten, bis die Seite fertig ist")).toBeVisible({ timeout: 60_000 });

  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations.map((v) => v.id)).toEqual([]);
  await dialog.getByRole("button", { name: "Fertig" }).click();

  await page.getByRole("button", { name: "Als Text" }).click();
  await expect(page.getByRole("textbox", { name: "Die Schritte" })).toHaveValue(
    [
      'tippe in "E-Mail" {email}',
      'tippe in "Passwort" {passwort}',
      'klicke "Anmelden"',
      "messen ab hier",
      'tippe in "Nachricht" "Was ist ein Lasttest?"',
      "drücke Enter",
      "warte bis die Seite ruhig ist (2 s)",
    ].join("\n"),
  );
  // Die beim Vorführen eingegebenen Zugangsdaten stehen schon im Formular
  await expect(page.getByLabel("Wert für {passwort}")).toHaveValue("sehr-geheim-42");

  await page.getByRole("checkbox", { name: /eigene Anwendung/ }).check();
  await page.getByRole("button", { name: "Test starten" }).click();
  await expect(page).toHaveURL(/\/lauf$/);
  await page.getByRole("link", { name: /Ergebnis ansehen/ }).click({ timeout: 150_000 });
  await expect(page.getByText(/POST \/api\/conversations\/\{v1\}\/messages/)).toBeVisible();
});
