// Baut das Benutzerhandbuch: handbuch.html → ../LAST-Benutzerhandbuch.pdf
// Aufruf (nach „npm ci“ in web/, dort liegt Playwright): node landing/handbuch/build.mjs
// Die Seitenzahlen im Inhaltsverzeichnis werden aus dem fertigen PDF gelesen (PyMuPDF) und im zweiten Durchgang eingesetzt.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(here, "../../web/package.json"))("playwright");
const out = path.join(here, "..", "LAST-Benutzerhandbuch.pdf");

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(pathToFileURL(path.join(here, "handbuch.html")).href);
await page.evaluate(() => document.fonts.ready);

// Jede Seite muss in den Satzspiegel passen (A4 abzüglich Ränder), sonst rutscht Text auf eine Folgeseite
await page.setViewportSize({ width: 665, height: 1000 });
await page.emulateMedia({ media: "print" });
const mm = 25.4 / 96,
  platz = 297 - 16 - 20;
const zuViel = await page.$$eval(".pg", (pgs) => pgs.map((p, i) => [i + 2, p.getBoundingClientRect().height]));
const ueber = zuViel.map(([s, hpx]) => [s, Math.round((hpx * mm - platz) * 10) / 10]).filter(([, d]) => d > 0);
if (ueber.length) console.warn("Seiten zu voll (Seite, mm zu viel):", JSON.stringify(ueber));
console.log("Auslastung je Seite (%):", JSON.stringify(zuViel.map(([, hpx]) => Math.round(((hpx * mm) / platz) * 100))));

const render = () => page.pdf({ path: out, format: "A4", printBackground: true, preferCSSPageSize: true });

// Durchgang 1: Seiten ermitteln, auf denen die Kapitel beginnen
await render();
const kapitel = await page.$$eval(".pg .kap", (els) =>
  els.map((e) => [e.querySelector(".nr").textContent.trim(), e.querySelector("h1").textContent.trim()]),
);
const script = `
import sys, json, re, fitz
doc = fitz.open(sys.argv[1]); res = {}
for nr, titel in json.loads(sys.argv[2]):
    for i in range(2, doc.page_count):
        if re.search(re.escape(nr) + r"\\s+" + re.escape(titel), doc[i].get_text()): res[nr] = i + 1; break
print(json.dumps(res))`;
const seiten = JSON.parse(execFileSync("python", ["-c", script, out, JSON.stringify(kapitel)], { encoding: "utf-8" }));

// Durchgang 2: Zahlen ins Inhaltsverzeichnis, neu drucken
await page.$$eval(
  ".toc li",
  (lis, s) =>
    lis.forEach((li) => {
      const z = s[li.querySelector(".n").textContent.trim()];
      if (z) li.querySelector(".s").textContent = z;
    }),
  seiten,
);
await render();

const n = execFileSync("python", ["-c", "import sys,fitz;print(fitz.open(sys.argv[1]).page_count)", out], { encoding: "utf-8" }).trim();
console.log(`geschrieben: ${out} · ${n} Seiten · Kapitel auf Seite`, JSON.stringify(seiten));
await browser.close();
