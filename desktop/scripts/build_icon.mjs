// Alle Bilder der Desktop-App aus dem Logo der Oberfläche (web/src/app/icon.svg) – nichts davon liegt im Repository:
//   icon.png                   1024 × 1024, daraus macht electron-builder .icns (macOS) und die Linux-Icons
//   icon.ico                   Windows: Programmdatei, Startmenü, Taskleiste (16 bis 256 px)
//   installerIcon.ico, uninstallerIcon.ico, installerHeaderIcon.ico
//   installerSidebar.bmp       Seitenbild des Installations-Assistenten (164 × 314)
//   uninstallerSidebar.bmp     dasselbe für die Deinstallation
//   installerHeader.bmp        Kopfbild der übrigen Seiten (150 × 57)
// electron-builder findet diese Namen im Ordner build/icons (buildResources) von selbst.
// Gerendert mit dem Chromium von Playwright (aus web/node_modules), damit kein weiteres Werkzeug nötig ist.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const desktop = join(dirname(fileURLToPath(import.meta.url)), "..");
const web = join(desktop, "..", "web");
const require = createRequire(join(web, "package.json"));
const { chromium } = require("playwright");

const svg = readFileSync(join(web, "src", "app", "icon.svg"), "utf8");
const font = pathToFileURL(
  join(web, "node_modules", "@fontsource-variable", "space-grotesk", "files", "space-grotesk-latin-wght-normal.woff2"),
).href;
const out = join(desktop, "build", "icons");
mkdirSync(out, { recursive: true });

const logo = (size) => svg.replace("<svg ", `<svg style="width:${size}px;height:${size}px;display:block" `);
const SIZES = [16, 24, 32, 48, 64, 128, 256];

/** Die dunkle Fläche mit dem Schein in Violett und Cyan – wie die Oberfläche. */
const backdrop = `background:
  radial-gradient(120% 55% at 100% 0%, rgba(124,92,255,.55), transparent 62%),
  radial-gradient(120% 50% at 0% 100%, rgba(34,211,238,.38), transparent 62%), #0b0d14;`;

const pages = {
  sidebar: {
    w: 164,
    h: 314,
    html: `<div style="width:164px;height:314px;${backdrop}position:relative;font-family:G,sans-serif;color:#fff">
      <div style="position:absolute;left:30px;top:44px;filter:drop-shadow(0 8px 22px rgba(124,92,255,.65))">${logo(104)}</div>
      <div style="position:absolute;left:0;right:0;top:166px;text-align:center;font-size:40px;font-weight:700;letter-spacing:-.03em">LAST</div>
      <div style="position:absolute;left:14px;right:14px;top:222px;text-align:center;font-size:11.5px;line-height:16px;color:rgba(255,255,255,.72)">
        Lasttest für KI-Server, Websites, APIs und Abläufe</div>
      <div style="position:absolute;left:34px;right:34px;bottom:30px;height:3px;border-radius:3px;background:linear-gradient(90deg,#7c5cff,#22d3ee)"></div>
    </div>`,
  },
  header: {
    w: 150,
    h: 57,
    html: `<div style="width:150px;height:57px;${backdrop}display:flex;align-items:center;gap:10px;padding-left:12px;box-sizing:border-box;font-family:G,sans-serif;color:#fff">
      ${logo(34)}<span style="font-size:22px;font-weight:700;letter-spacing:-.02em">LAST</span></div>`,
  },
};

const browser = await chromium.launch();
const shot = async (width, height, html) => {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.setContent(`<html><head><style>@font-face{font-family:G;src:url(${font});font-weight:300 700}
    body{margin:0;background:transparent}</style></head><body>${html}</body></html>`);
  await page.evaluate(() => document.fonts.ready);
  const png = await page.screenshot({ omitBackground: true });
  await page.close();
  return png;
};

/** PNG → 24-Bit-BMP (so verlangt es der NSIS-Assistent: ohne Transparenz, Zeilen auf 4 Byte aufgefüllt, von unten). */
async function bmp(png) {
  const page = await browser.newPage();
  const { w, h, rgba } = await page.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = Object.assign(document.createElement("canvas"), { width: img.width, height: img.height });
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0);
    return { w: img.width, h: img.height, rgba: Array.from(ctx.getImageData(0, 0, img.width, img.height).data) };
  }, png.toString("base64"));
  await page.close();
  const row = Math.ceil((w * 3) / 4) * 4;
  const buf = Buffer.alloc(54 + row * h);
  buf.write("BM");
  buf.writeUInt32LE(buf.length, 2);
  buf.writeUInt32LE(54, 10);
  buf.writeUInt32LE(40, 14);
  buf.writeInt32LE(w, 18);
  buf.writeInt32LE(h, 22);
  buf.writeUInt16LE(1, 26);
  buf.writeUInt16LE(24, 28);
  buf.writeUInt32LE(row * h, 34);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const s = (y * w + x) * 4,
        d = 54 + (h - 1 - y) * row + x * 3;
      buf[d] = rgba[s + 2];
      buf[d + 1] = rgba[s + 1];
      buf[d + 2] = rgba[s];
    }
  }
  return buf;
}

/** Mehrere PNGs in eine .ico (Windows liest PNG-Bilder darin seit Vista). */
function ico(images) {
  const head = Buffer.alloc(6 + 16 * images.length);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(images.length, 4);
  let offset = head.length;
  images.forEach(({ size, png }, i) => {
    const at = 6 + 16 * i;
    head[at] = size === 256 ? 0 : size;
    head[at + 1] = size === 256 ? 0 : size;
    head.writeUInt16LE(1, at + 4);
    head.writeUInt16LE(32, at + 6);
    head.writeUInt32LE(png.length, at + 8);
    head.writeUInt32LE(offset, at + 12);
    offset += png.length;
  });
  return Buffer.concat([head, ...images.map((i) => i.png)]);
}

// macOS-Icons haben Luft am Rand (etwa 10 %), sonst wirken sie größer als alle anderen im Dock
const big = await shot(1024, 1024, `<div style="display:grid;place-items:center;height:1024px"><div>${logo(824)}</div></div>`);
writeFileSync(join(out, "icon.png"), big);

// Windows-Icons füllen die ganze Fläche
const icon = ico(await Promise.all(SIZES.map(async (size) => ({ size, png: await shot(size, size, logo(size)) }))));
for (const name of ["icon", "installerIcon", "uninstallerIcon", "installerHeaderIcon"]) writeFileSync(join(out, `${name}.ico`), icon);

const sidebar = await bmp(await shot(pages.sidebar.w, pages.sidebar.h, pages.sidebar.html));
writeFileSync(join(out, "installerSidebar.bmp"), sidebar);
writeFileSync(join(out, "uninstallerSidebar.bmp"), sidebar);
writeFileSync(join(out, "installerHeader.bmp"), await bmp(await shot(pages.header.w, pages.header.h, pages.header.html)));
// Zur Ansicht (nicht Teil der App)
writeFileSync(join(out, "vorschau-seitenbild.png"), await shot(pages.sidebar.w, pages.sidebar.h, pages.sidebar.html));

await browser.close();
console.log(`Fertig: ${out}`);
