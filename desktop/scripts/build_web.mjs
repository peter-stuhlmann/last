// Die Oberfläche (web/) als eigenständigen Next.js-Server für die Desktop-App bauen und nach build/web legen.
// Next legt bei output: "standalone" nur Server und Abhängigkeiten ab – statische Dateien und public/ gehören dazu.
import { execSync } from "node:child_process";
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const desktop = join(dirname(fileURLToPath(import.meta.url)), "..");
const webDir = join(desktop, "..", "web");
const out = join(desktop, "build", "web");

execSync("npm ci", { cwd: webDir, stdio: "inherit" });
execSync("npx next build", { cwd: webDir, stdio: "inherit", env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" } });

rmSync(out, { recursive: true, force: true });
cpSync(join(webDir, ".next", "standalone"), out, { recursive: true, verbatimSymlinks: true });
cpSync(join(webDir, ".next", "static"), join(out, ".next", "static"), { recursive: true });
if (existsSync(join(webDir, "public"))) cpSync(join(webDir, "public"), join(out, "public"), { recursive: true });
console.log(`Fertig: ${out}`);
