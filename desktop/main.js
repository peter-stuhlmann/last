// LAST als Desktop-App: startet das eingepackte Python-Backend und den Next.js-Server auf freien Ports des
// eigenen Rechners und zeigt die Oberfläche in einem Fenster. Kein Docker, kein installiertes Python oder Node.
//
//   Backend   build/backend/last-backend   (PyInstaller, siehe scripts/build_backend.py)
//   Chromium  build/browsers               (für Abläufe)
//   Web       build/web/server.js          (Next.js „standalone“, läuft im Node von Electron)
//
// Das Backend antwortet nur mit einem Schlüssel, den diese App bei jedem Start neu erzeugt – andere Programme oder
// Webseiten auf dem Rechner können es so nicht fernsteuern.
const { app, BrowserWindow, dialog, shell, utilityProcess } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const RES = app.isPackaged ? process.resourcesPath : path.join(__dirname, "build");
const BACKEND = path.join(RES, "backend", process.platform === "win32" ? "last-backend.exe" : "last-backend");
const BROWSERS = path.join(RES, "browsers");
const WEB = path.join(RES, "web", "server.js");
const START_TIMEOUT_MS = 90_000;
// Rauchtest (CI): starten, Oberfläche laden, Bildschirmfoto in diese Datei, beenden – Exit-Code 0 nur bei Erfolg
const SMOKE = process.env.LAST_SMOKE_TEST;

let win = null;
let backend = null;
let web = null;
let quitting = false;

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function logFile(name) {
  const dir = app.getPath("logs");
  fs.mkdirSync(dir, { recursive: true });
  return fs.createWriteStream(path.join(dir, name), { flags: "w" });
}

async function waitFor(url, headers = {}) {
  const until = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < until) {
    if (quitting) throw new Error("abgebrochen");
    try {
      const res = await fetch(url, { headers, signal: AbortSignal.timeout(2000) });
      if (res.ok) return;
    } catch {
      // startet noch
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${url} antwortet nicht`);
}

function stopAll() {
  quitting = true;
  for (const p of [web, backend]) {
    try {
      p?.kill();
    } catch {
      // schon weg
    }
  }
}

async function start() {
  const results = path.join(app.getPath("documents"), "LAST");
  fs.mkdirSync(results, { recursive: true });
  const token = crypto.randomBytes(32).toString("hex");
  const [backendPort, webPort] = [await freePort(), await freePort()];

  const backendLog = logFile("backend.log");
  backend = spawn(BACKEND, ["--host", "127.0.0.1", "--port", String(backendPort), "--results", results], {
    env: { ...process.env, PLAYWRIGHT_BROWSERS_PATH: BROWSERS, LAST_BACKEND_TOKEN: token, PYTHONUNBUFFERED: "1" },
    windowsHide: true,
  });
  backend.stdout.pipe(backendLog);
  backend.stderr.pipe(backendLog);
  backend.on("exit", (code) => !quitting && fail(`Das Test-Backend wurde beendet (Code ${code}).`));

  const webLog = logFile("web.log");
  web = utilityProcess.fork(WEB, [], {
    cwd: path.dirname(WEB),
    stdio: "pipe",
    serviceName: "LAST Oberfläche",
    env: {
      ...process.env,
      NODE_ENV: "production",
      NEXT_TELEMETRY_DISABLED: "1",
      HOSTNAME: "127.0.0.1",
      PORT: String(webPort),
      BACKEND_URL: `http://127.0.0.1:${backendPort}`,
      BACKEND_TOKEN: token,
    },
  });
  web.stdout?.pipe(webLog);
  web.stderr?.pipe(webLog);
  web.on("exit", (code) => !quitting && fail(`Die Oberfläche wurde beendet (Code ${code}).`));

  await waitFor(`http://127.0.0.1:${backendPort}/api/state`, { "X-Last-Token": token });
  await waitFor(`http://127.0.0.1:${webPort}/api/health`);
  return `http://127.0.0.1:${webPort}/`;
}

function fail(message) {
  if (quitting) return;
  stopAll();
  if (SMOKE) {
    console.error(`LAST-Rauchtest fehlgeschlagen: ${message}`);
    app.exit(1);
    return;
  }
  dialog.showErrorBox("LAST konnte nicht starten", `${message}\n\nProtokolle: ${app.getPath("logs")}`);
  app.quit();
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 900,
    minHeight: 640,
    backgroundColor: "#0b0d14",
    title: "LAST",
    show: false,
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  win.once("ready-to-show", () => win.show());
  win.loadFile(path.join(__dirname, "loading.html"));
  return win;
}

function keepInside(origin) {
  const external = (url) => !url.startsWith(origin) && /^https?:/.test(url);
  // Links nach draußen (z. B. die getestete Seite) im normalen Browser öffnen, nicht im App-Fenster
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (external(url)) shell.openExternal(url);
    return { action: external(url) ? "deny" : "allow" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    if (external(url)) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
  app.whenReady().then(async () => {
    createWindow();
    try {
      const url = await start();
      keepInside(url.replace(/\/$/, ""));
      await win.loadURL(url);
      if (SMOKE) {
        await new Promise((r) => setTimeout(r, 1500));
        fs.writeFileSync(SMOKE, (await win.webContents.capturePage()).toPNG());
        const title = await win.webContents.executeJavaScript("document.title");
        console.log(`LAST-Rauchtest ok: ${url} · ${title}`);
        stopAll();
        app.exit(0);
      }
    } catch (e) {
      fail(String(e?.message ?? e));
    }
  });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", stopAll);
}
