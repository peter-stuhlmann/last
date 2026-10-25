// Rauchtest der gepackten App (dist/*-unpacked bzw. LAST.app): starten, Oberfläche laden, Bildschirmfoto, beenden.
// Schlägt fehl, wenn Backend oder Oberfläche nicht hochkommen. Aufruf: node scripts/smoke.mjs [bild.png]
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const dist = join(dirname(fileURLToPath(import.meta.url)), "..", "dist");
const shot = resolve(process.argv[2] ?? join(dist, "smoke.png"));

function executable() {
  if (process.platform === "darwin") {
    const dir = readdirSync(dist).find((d) => d.startsWith("mac") && existsSync(join(dist, d, "LAST.app")));
    return dir && join(dist, dir, "LAST.app", "Contents", "MacOS", "LAST");
  }
  if (process.platform === "win32") return join(dist, "win-unpacked", "LAST.exe");
  return join(dist, "linux-unpacked", "last");
}

const exe = executable();
if (!exe || !existsSync(exe)) {
  console.error(`Keine gepackte App in ${dist} – erst „npx electron-builder --dir“.`);
  process.exit(1);
}
// Auf Linux-CI-Rechnern fehlt die SUID-Sandbox von Chromium; für den Test reicht --no-sandbox
const args = process.platform === "linux" ? ["--no-sandbox"] : [];
const env = { ...process.env, LAST_SMOKE_TEST: shot };
delete env.ELECTRON_RUN_AS_NODE; // in VS-Code-Terminals gesetzt – Electron liefe sonst als reines Node
// Ein altes Bild darf nicht als Erfolg zählen – etwa wenn LAST schon läuft und die zweite Instanz sich sofort beendet
rmSync(shot, { force: true });
const r = spawnSync(exe, args, { env, stdio: "inherit", timeout: 180_000 });
if (r.status !== 0 || !existsSync(shot)) {
  console.error(`Rauchtest fehlgeschlagen (Exit ${r.status ?? r.signal})`);
  process.exit(1);
}
console.log(`Bildschirmfoto: ${shot}`);
