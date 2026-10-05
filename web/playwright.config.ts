import { defineConfig, devices } from "@playwright/test";

// Durchlauf-Tests gegen die echte Anwendung in Docker (siehe ../docker-compose.e2e.yml).
// Vorher starten:  npm run e2e:up      Danach aufräumen:  npm run e2e:down
export default defineConfig({
  testDir: "./e2e",
  // Ein echter Kurzlauf dauert etwa eine halbe Minute; es kann immer nur ein Test gleichzeitig laufen.
  timeout: 180_000,
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8099",
    trace: "retain-on-failure",
    actionTimeout: 20_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
