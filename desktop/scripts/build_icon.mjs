// App-Icon (1024 × 1024 PNG) aus dem Logo der Oberfläche – electron-builder macht daraus .icns/.ico.
// Gerendert mit dem Chromium von Playwright (aus web/node_modules), damit kein weiteres Werkzeug nötig ist.
import { mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const desktop = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(join(desktop, "..", "web", "package.json"));
const { chromium } = require("playwright");

const svg = readFileSync(join(desktop, "..", "web", "src", "app", "icon.svg"), "utf8");
const out = join(desktop, "build", "icons");
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
// macOS-Icons haben Luft am Rand (etwa 10 %), sonst wirken sie größer als alle anderen im Dock
await page.setContent(
  `<html><body style="margin:0;background:transparent;display:grid;place-items:center;height:100vh">
     <div style="width:824px;height:824px">${svg.replace("<svg ", '<svg style="width:100%;height:100%" ')}</div></body></html>`,
);
await page.screenshot({ path: join(out, "icon.png"), omitBackground: true });
await browser.close();
console.log(`Fertig: ${join(out, "icon.png")}`);
