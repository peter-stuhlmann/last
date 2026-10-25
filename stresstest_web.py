#!/usr/bin/env python3
"""
Weboberfläche für llm_stresstest.py
===================================

Startet einen kleinen Webserver. Im Browser trägst du die Testparameter ein,
drückst Enter – der Test läuft auf diesem Rechner, die Ergebnisse erscheinen
live auf der Seite. Am Ende gibt es die PowerPoint-Präsentation zum Download.

    pip install aiohttp python-pptx reportlab
    python3 stresstest_web.py                    # → http://localhost:8090
    python3 stresstest_web.py --host 0.0.0.0     # auch vom Laptop aus erreichbar

Benötigt llm_stresstest.py und stresstest_ui.html im selben Ordner.
"""

import argparse
import asyncio
import datetime as dt
import hmac
import json
import os
import re
import shutil
import sys
import time

try:
    import pptx  # noqa: F401  (für den Bericht)
    from aiohttp import ClientSession, ClientTimeout, web
except ImportError:
    exe = sys.executable if " " not in sys.executable else f'"{sys.executable}"'
    sys.exit("Es fehlen Python-Pakete für genau dieses Python (" + sys.executable + ").\n"
             "Installieren mit:\n    " + exe + " -m pip install aiohttp python-pptx reportlab")

import flow_stresstest as flow
import llm_stresstest as lt
import web_stresstest as ws

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_NAME = "LLM-Haertetest.pptx"
PDF_NAME = "LLM-Haertetest.pdf"
RUN_NAME_RE = re.compile(r"^results_[\w-]+$")
# Was dieses Backend kann: Abläufe brauchen den Browser (Image-Ziel „browser“, siehe Dockerfile)
FEATURES = {"flow": flow.browser_available()}

# Gelöschte Läufe liegen eine Woche im Papierkorb – lokal gibt es selten ein Backup
TRASH_DIR = ".papierkorb"
TRASH_DAYS = 7
NOTES_FILE = "notes.json"
TAG_RE = re.compile(r"^[a-z0-9äöüß][a-z0-9äöüß._-]{0,23}$")
MAX_TITLE, MAX_NOTE, MAX_TAGS = 80, 2000, 10
LIVE_TIMEOUT = 150           # Vorführen: so lange darf ein Schritt dauern (eine Chat-Antwort zum Beispiel)


class Runner:
    """Hält den aktuellen Testlauf (es läuft immer höchstens einer)."""

    def __init__(self, results_root):
        self.root = results_root
        self.task = None
        self.st = None
        self.args = None
        self.run_id = 0
        self.logs = []
        self.version = 0
        self.state = "idle"      # idle | running | done | stopped | error
        self.error = None
        self.outdir = None
        self.report = None
        self.pdf = None
        lt.LOG_SINKS.append(self._on_log)

    def _on_log(self, line):
        self.logs.append(line)
        if len(self.logs) > 5000:
            del self.logs[:1000]

    def bump(self):
        self.version += 1

    @property
    def running(self):
        return self.task is not None and not self.task.done()

    def start(self, a):
        name = f"results_{dt.datetime.now():%Y%m%d_%H%M%S}"
        self.outdir = os.path.join(self.root, name)
        os.makedirs(self.outdir, exist_ok=True)
        a.out = self.outdir
        self.args = a
        self.run_id += 1
        self.logs = []
        self.state = "running"
        self.error = None
        self.report = None
        self.pdf = None
        self.st = (flow.FlowStressTest if a.kind == "flow" else ws.WebStressTest if a.kind == "api" or a.kind == "web" else lt.StressTest)(a, self.outdir)
        self.st.on_update = self.bump
        self.bump()
        self.task = asyncio.create_task(self._run())
        return name

    async def _run(self):
        lt.log(f"Starte Test gegen {self.args.base_url} → {os.path.basename(self.outdir)}")
        try:
            await self.st.run()
            self.state = "done"
        except lt.PreflightError as e:
            self.state, self.error = "error", str(e)
            lt.log(f"✗ {e}")
        except asyncio.CancelledError:
            self.state = "stopped"
            lt.log("Test abgebrochen – Bericht wird mit den bisherigen Daten erstellt.")
        except Exception as e:  # noqa
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
            lt.log(f"✗ Unerwarteter Fehler: {self.error}")
        finally:
            s = self.st.summary
            if any(k in s for k in ("baseline", "ramp", "rate", "context", "spike", "soak")):
                path = os.path.join(self.outdir, REPORT_NAME)
                pdf_path = os.path.join(self.outdir, PDF_NAME)
                run = asyncio.get_running_loop().run_in_executor
                try:
                    lt.log("Erstelle PowerPoint-Bericht …")
                    if self.args.kind in ("web", "api", "flow"):
                        import report_web
                        await run(None, report_web.build_report, s, path)
                    else:
                        await run(None, lt.build_report, s, path, self.args)
                    self.report = path
                    lt.log("✓ Bericht fertig.")
                    if self.args.kind in ("web", "api", "flow"):
                        pdf = await run(None, report_web.build_pdf, s, pdf_path)
                    else:
                        pdf = await run(None, lt.build_pdf_report, s, pdf_path)
                    if pdf:
                        self.pdf = pdf
                        lt.log("✓ Kurzbericht (PDF, 1 Seite) fertig.")
                except Exception as e:  # noqa
                    lt.log(f"✗ Bericht konnte nicht erstellt werden: {e}")
            self.bump()

    def stop(self):
        if self.running:
            self.task.cancel()


# ── Hilfen ──────────────────────────────────────────────────────────────────

def check_features(cfg):
    """Lehnt Testarten ab, die dieses Image nicht kann – vor dem Start, mit klarer Ansage."""
    if (cfg.get("kind") or "llm") == "flow" and not FEATURES["flow"]:
        raise ValueError(flow.NO_BROWSER)


def build_args(cfg):
    """JSON aus dem Formular → argparse-Namespace mit denselben Defaults wie die CLI."""
    kind = cfg.get("kind") or "llm"
    # Ein Lasttest sieht für fremde Server, Websites und APIs aus wie ein Angriff – ohne ausdrückliche
    # Bestätigung startet er nicht.
    if kind in ("llm", "web", "api", "flow") and cfg.get("confirm_owner") is not True:
        thing = {"llm": "diesen Server", "api": "diese API", "flow": "diese Anwendung"}.get(kind, "diese Website")
        raise ValueError(f"Bitte bestätigen, dass ihr {thing} testen dürft.")
    if kind in ("web", "api", "flow"):
        return ws.build_args(cfg)
    if kind != "llm":
        raise ValueError(f"Unbekannte Art von Test: {kind!r}")
    p = lt.build_parser()
    a = p.parse_args([])
    blocked = {"report_only", "out", "quick", "kind"}
    for key, val in cfg.items():
        if key in blocked or not hasattr(a, key):
            continue
        default = p.get_default(key)
        if val is None or val == "":
            setattr(a, key, default)
            continue
        try:
            if isinstance(default, bool):
                val = bool(val)
            elif isinstance(default, int):
                val = int(float(val))
            elif isinstance(default, float):
                val = float(val)
            elif key in ("max_context", "seed"):
                val = int(float(val))
            else:
                val = str(val).strip()
        except (TypeError, ValueError):
            raise ValueError(f"Ungültiger Wert für {key}: {val!r}") from None
        setattr(a, key, val)
    if not a.base_url.startswith(("http://", "https://")):
        raise ValueError("Server-URL muss mit http:// oder https:// beginnen")
    if a.length_mix not in ("fixed", "mixed"):
        raise ValueError(f"Ungültiger Wert für length_mix: {a.length_mix!r}")
    if str(a.rates).strip().lower() != "auto":
        try:
            if not [float(x) for x in str(a.rates).split(",") if x.strip()]:
                raise ValueError
        except ValueError:
            raise ValueError("„Wie viele Fragen pro Minute?“: Zahlen mit Komma oder auto") from None
    a.kind = "llm"
    return a


def run_kind(path):
    """Art eines gespeicherten Laufs: "web" oder "llm" (auch für Läufe aus älteren Versionen)."""
    try:
        with open(os.path.join(path, "summary.json"), encoding="utf-8") as f:
            return json.load(f).get("config", {}).get("kind") or "llm"
    except Exception:
        return "llm"


def report_filename(path, name, ext):
    prefix = {"web": "Lasttest-Website", "api": "Lasttest-API", "flow": "Lasttest-Ablauf"}.get(run_kind(path), "LLM-Haertetest")
    return f"{prefix}_{name[8:]}.{ext}"


def comparison_builder(kinds):
    """Passende Funktion für den Vergleichsbericht. Website- und KI-Server-Läufe messen
    Verschiedenes und lassen sich nicht miteinander vergleichen."""
    if len(set(kinds)) > 1:
        raise ValueError("Bitte nur Läufe gleicher Art vergleichen: entweder Websites oder KI-Server.")
    if kinds and kinds[0] in ("web", "api", "flow"):
        import report_web
        return report_web.build_comparison
    return lt.build_comparison


def public_summary(summary):
    return {k: v for k, v in summary.items() if k != "monitor"}


def compact_samples(samples):
    keys = ("t", "phase", "gpu_util", "gpu_temp", "gpu_clock", "gpu_power", "ram_used_gb",
            "kv", "running", "waiting")
    return [{k: s[k] for k in keys if s.get(k) is not None} for s in samples]


# ── HTTP-Handler ────────────────────────────────────────────────────────────

routes = web.RouteTableDef()


@routes.get("/")
async def index(req):
    return web.FileResponse(os.path.join(HERE, "stresstest_ui.html"))


@routes.get("/api/defaults")
async def defaults(req):
    p = lt.build_parser()
    a = vars(p.parse_args([]))
    a.pop("api_key", None)
    return web.json_response({"defaults": a, "quick": lt.QUICK_PROFILE,
                              "web": {"defaults": ws.DEFAULTS, "quick": ws.QUICK_PROFILE},
                              "api": {"defaults": {**ws.DEFAULTS, **ws.API_DEFAULTS}, "quick": ws.QUICK_PROFILE},
                              "flow": {"defaults": {**ws.DEFAULTS, **flow.FLOW_DEFAULTS},
                                       "quick": {**ws.QUICK_PROFILE, "levels": "1,2,4,8,16", "spike_size": 8}},
                              "features": FEATURES})


@routes.get("/api/models")
async def models(req):
    base = req.query.get("base_url", "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        return web.json_response({"error": "Ungültige URL"}, status=400)
    headers = {}
    if req.query.get("api_key"):
        headers["Authorization"] = f"Bearer {req.query['api_key']}"
    try:
        async with ClientSession(timeout=ClientTimeout(total=5)) as s:
            async with s.get(base + "/models", headers=headers) as r:
                data = await r.json(content_type=None)
        items = [{"id": m.get("id"),
                  "max_len": m.get("max_model_len") or m.get("context_length")}
                 for m in (data.get("data") or [])]
        return web.json_response({"models": items})
    except Exception as e:  # noqa
        return web.json_response({"error": f"Server nicht erreichbar: {e}"}, status=502)


@routes.post("/api/start")
async def start(req):
    runner = req.app["runner"]
    if runner.running:
        return web.json_response({"error": "Es läuft bereits ein Test."}, status=409)
    try:
        cfg = await req.json()
        check_features(cfg)
        a = build_args(cfg)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    await close_live(req.app)                    # ein offener Vorführ-Browser würde die Messung stören
    name = runner.start(a)
    return web.json_response({"ok": True, "run": name})


LIVE_KEYS = {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Space", "Backspace"}
_TARGET_FIELDS = {"target": str, "near": str, "nth": int}


def clean_live_action(a):
    """Eine Aktion beim Vorführen – streng geprüft, weil sie direkt im Browser ausgeführt wird."""
    if not isinstance(a, dict) or a.get("type") not in ("pick", "pick_at", "fill", "press", "scroll"):
        raise ValueError("Unbekannte Aktion.")
    if a["type"] == "scroll":
        vals = [a.get(k) for k in ("x", "y", "dy")]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals) or \
                not (0 <= vals[0] <= 1280 and 0 <= vals[1] <= 800 and -5000 <= vals[2] <= 5000):
            raise ValueError("Ungültiges Blättern.")
        return {"type": "scroll", "x": float(vals[0]), "y": float(vals[1]), "dy": float(vals[2])}
    if a["type"] == "pick_at":
        vals = [a.get(k) for k in ("x", "y")]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals) or                 not (0 <= vals[0] <= 1280 and 0 <= vals[1] <= 800):
            raise ValueError("Ungültige Stelle.")
        return {"type": "pick_at", "x": float(vals[0]), "y": float(vals[1]), "measuring": a.get("measuring") is True}
    if a["type"] == "pick":
        if not isinstance(a.get("mark"), str) or not a["mark"].isdigit() or len(a["mark"]) > 7:
            raise ValueError("Unbekanntes Element.")
        return {"type": "pick", "mark": a["mark"], "measuring": a.get("measuring") is True}
    if a["type"] == "press":
        if a.get("key") not in LIVE_KEYS:
            raise ValueError("Unbekannte Taste.")
        return {"type": "press", "key": a["key"], "measuring": a.get("measuring") is True}
    t, text = a.get("target"), a.get("text")
    if not isinstance(t, dict) or not isinstance(t.get("target"), str) or not t["target"].strip():
        raise ValueError("Unbekanntes Feld.")
    target = {}
    for k, typ in _TARGET_FIELDS.items():
        v = t.get(k)
        if v is None:
            continue
        if not isinstance(v, typ) or isinstance(v, bool) or (typ is str and ('"' in v or len(v) > 200)) or \
                (typ is int and not 1 <= v <= 999):
            raise ValueError(f"Ungültiger Wert für {k}.")
        target[k] = v
    if not isinstance(text, str) or len(text) > 4000 or "\n" in text:
        raise ValueError("Der Text muss eine Zeile sein (höchstens 4000 Zeichen).")
    return {"type": "fill", "target": target, "text": text, "enter": a.get("enter") is True,
            "measuring": a.get("measuring") is True}


_KEY_RE = re.compile(r"^(?:[A-Za-z0-9]{1,12}|.)$")
_MODS = {"Control", "Shift", "Alt", "Meta"}


def clean_live_events(v):
    """Eingaben beim Live-Vorführen (Maus, Rad, Tasten, Text) – streng geprüft, weil sie direkt im Browser landen."""
    if not isinstance(v, list) or not 1 <= len(v) <= 60:
        raise ValueError("Ungültige Eingaben.")
    num = lambda x, lo, hi: isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi  # noqa: E731
    out = []
    for e in v:
        t = e.get("t") if isinstance(e, dict) else None
        if t in ("move", "click", "wheel"):
            if not (num(e.get("x"), 0, 1280) and num(e.get("y"), 0, 800)):
                raise ValueError("Ungültige Stelle.")
            ev = {"t": t, "x": float(e["x"]), "y": float(e["y"])}
            if t == "wheel":
                if not (num(e.get("dx", 0), -5000, 5000) and num(e.get("dy", 0), -5000, 5000)):
                    raise ValueError("Ungültiges Blättern.")
                ev.update(dx=float(e.get("dx", 0)), dy=float(e.get("dy", 0)))
            if t == "click":
                ev["dbl"] = e.get("dbl") is True
        elif t in ("type", "text"):
            text = e.get("text")
            if not isinstance(text, str) or not text or len(text) > 4000 or "\n" in text or "\r" in text:
                raise ValueError("Ungültiger Text.")
            ev = {"t": t, "text": text}
        elif t == "key":
            key, mods = e.get("key"), e.get("mods") or []
            if not isinstance(key, str) or not _KEY_RE.match(key) or not isinstance(mods, list) or                     not set(mods) <= _MODS or len(mods) > 3:
                raise ValueError("Ungültige Taste.")
            ev = {"t": "key", "key": key, "mods": mods}
        else:
            raise ValueError("Unbekannte Eingabe.")
        out.append(ev)
    return out


def clean_secrets(v):
    v = v or {}
    if not isinstance(v, dict) or not all(isinstance(k, str) and isinstance(x, str) for k, x in v.items()):
        raise ValueError("Platzhalter-Werte müssen Text sein.")
    return v


class LiveSlot:
    """Platz für die eine Vorführ-Sitzung (aiohttp mag es nicht, wenn eine laufende App neue Werte bekommt)."""
    session = None


async def close_live(app):
    slot = app["live"]
    live, slot.session = slot.session, None
    if live is not None:
        async with live.lock:
            await live.close()


async def _live_reaper(app):
    """Räumt eine vergessene Sitzung ab – ein offener Browser kostet Speicher."""
    while True:
        await asyncio.sleep(30)
        if app["live"].session is not None and app["live"].session.expired:
            await close_live(app)


@routes.post("/api/flow/live/{op:start|act|look|stop}")
async def flow_live(req):
    """Vorführen: start öffnet die Seite und spielt die bisherigen Schritte ab, act führt einen Klick, eine
    Eingabe oder eine Taste aus, stop schließt den Browser."""
    app, op = req.app, req.match_info["op"]
    if op == "stop":
        await close_live(app)
        return web.json_response({"ok": True})
    if not FEATURES["flow"]:
        return web.json_response({"error": flow.NO_BROWSER}, status=400)
    if app["runner"].running:
        return web.json_response({"error": "Während ein Test läuft, geht Vorführen nicht – das würde die Messung "
                                           "verfälschen."}, status=409)
    try:
        cfg = await req.json()
        if not isinstance(cfg, dict):
            raise ValueError("Ungültige Anfrage.")
        secrets = clean_secrets(cfg.get("secrets"))
        if op == "start":
            steps = flow.parse_steps(cfg.get("steps") or "", partial=True)
            site_auth = flow.clean_site_auth(cfg.get("site_auth"))
        elif op == "look":
            pass
        else:
            action = clean_live_action(cfg.get("action"))
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    import flow_live  # Playwright nur laden, wenn wirklich vorgeführt wird
    if op == "start":
        await close_live(app)
        live = app["live"].session = flow_live.LiveSession()
        failed = None
        async with live.lock:
            try:
                result = await asyncio.wait_for(live.open(steps, secrets, site_auth), LIVE_TIMEOUT)
                if cfg.get("stream") is True:
                    await live.start_stream()
            except lt.PreflightError as e:
                failed = str(e)
            except TimeoutError:
                failed = f"Die Seite hat nach {LIVE_TIMEOUT} s nicht geantwortet."
            except Exception as e:  # noqa – z. B. Browser startet nicht; dann nichts offen lassen
                failed = f"Der Browser ließ sich nicht starten: {type(e).__name__}."
        if failed:                               # erst nach dem Freigeben schließen – close_live braucht die Sperre
            await close_live(app)
            return web.json_response({"error": failed}, status=400)
        return web.json_response(result)
    live = app["live"].session
    if live is None or cfg.get("session") != live.id:
        return web.json_response({"error": "Der Browser wurde inzwischen geschlossen – bitte neu starten."}, status=410)
    if op == "look":                             # nur ein Bild – ohne Sperre, damit es auch während einer Aktion geht
        return web.json_response(await live.look())
    if live.lock.locked():
        return web.json_response({"error": "Einen Moment – der letzte Schritt läuft noch."}, status=409)
    async with live.lock:
        try:
            result = await asyncio.wait_for(live.act(action, secrets), LIVE_TIMEOUT)
        except TimeoutError:
            result = None
    if result is None:                           # erst nach dem Freigeben schließen – close_live braucht die Sperre
        await close_live(app)
        return web.json_response({"error": f"Nach {LIVE_TIMEOUT} s keine Antwort – der Browser wurde geschlossen."},
                                 status=504)
    return web.json_response(result)


@routes.post("/api/flow/live/input")
async def flow_live_input(req):
    """Live-Vorführen: Maus, Rad, Tasten und Text der Oberfläche – direkt in den Browser, Schritte in Reihenfolge."""
    try:
        cfg = await req.json()
        if not isinstance(cfg, dict):
            raise ValueError("Ungültige Anfrage.")
        events = clean_live_events(cfg.get("events"))
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    live = req.app["live"].session
    if live is None or cfg.get("session") != live.id or live._cdp is None:
        return web.json_response({"error": "Der Browser wurde inzwischen geschlossen – bitte neu starten."}, status=410)
    live.put(events, cfg.get("measuring") is True)
    return web.json_response({"ok": True})


@routes.get("/api/flow/live/stream")
async def flow_live_stream(req):
    """Live-Vorführen als Server-Sent Events: „frame“ (JPEG, Base64) und „msg“ (JSON: Schritte, Felder, Hinweise)."""
    live = req.app["live"].session
    if live is None or req.query.get("session") != live.id or live._cdp is None:
        return web.json_response({"error": "Der Browser wurde inzwischen geschlossen – bitte neu starten."}, status=410)
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})
    await resp.prepare(req)
    live._sent = 0                                   # nach einem erneuten Verbinden das aktuelle Bild noch einmal
    live._wake.set()
    try:
        while req.app["live"].session is live:
            for kind, data in await live.events():
                if kind == "ping":
                    await resp.write(b": ping\n\n")
                else:
                    await resp.write(f"event: {kind}\ndata: {data}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


@routes.post("/api/stop")
async def stop(req):
    req.app["runner"].stop()
    return web.json_response({"ok": True})


@routes.get("/api/state")
async def state(req):
    """Kurzer Zustand ohne Stream – für die Startseite der Next.js-Oberfläche und den Healthcheck."""
    runner = req.app["runner"]
    return web.json_response({"state": runner.state, "error": runner.error,
                              "run": os.path.basename(runner.outdir or ""),
                              "version": lt.VERSION, "features": FEATURES})


@routes.get("/api/events")
async def events(req):
    """Server-Sent Events: Log-Zeilen, Teilergebnisse und Systemwerte live."""
    runner = req.app["runner"]
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                       "Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})
    await resp.prepare(req)
    run_id, n_logs, n_samples, ver = None, 0, 0, -1
    try:
        while True:
            msgs = []
            if runner.run_id != run_id:
                run_id, n_logs, n_samples, ver = runner.run_id, 0, 0, -1
                msgs.append({"type": "reset", "run": os.path.basename(runner.outdir or "")})
            if len(runner.logs) < n_logs:
                n_logs = 0
            if len(runner.logs) > n_logs:
                msgs.append({"type": "log", "lines": runner.logs[n_logs:]})
                n_logs = len(runner.logs)
            if runner.st is not None:
                samples = runner.st.mon.samples
                if len(samples) > n_samples:
                    msgs.append({"type": "samples",
                                 "samples": compact_samples(samples[n_samples:])})
                    n_samples = len(samples)
            if runner.version != ver:
                ver = runner.version
                msgs.append({
                    "type": "state", "state": runner.state, "error": runner.error,
                    "run": os.path.basename(runner.outdir or ""),
                    "report": bool(runner.report), "pdf": bool(runner.pdf),
                    "summary": public_summary(runner.st.summary) if runner.st else None})
            for m in msgs:
                await resp.write(f"data: {json.dumps(m, default=str)}\n\n".encode())
            if not msgs:
                await resp.write(b": ping\n\n")
            await asyncio.sleep(1)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


def _run_dir(req):
    name = req.match_info["name"]
    if not RUN_NAME_RE.match(name):
        raise web.HTTPNotFound()
    path = os.path.join(req.app["runner"].root, name)
    if not os.path.isdir(path):
        raise web.HTTPNotFound()
    return name, path


def read_notes(path):
    """Titel, Tags, Notiz eines Laufs – von Menschen ergänzt, getrennt von der Messung in summary.json."""
    try:
        with open(os.path.join(path, NOTES_FILE), encoding="utf-8") as f:
            n = json.load(f)
    except (OSError, ValueError):
        n = {}
    return {"title": n.get("title") or None, "tags": [t for t in (n.get("tags") or []) if isinstance(t, str)],
            "note": n.get("note") or "", "pinned": bool(n.get("pinned")), "updated": n.get("updated")}


def clean_notes(body):
    """Prüft die Eingabe streng – alles andere ist ein Fehler, nichts wird stillschweigend gekürzt."""
    if not isinstance(body, dict):
        raise ValueError("Notizen müssen ein Objekt sein.")
    unknown = set(body) - {"title", "tags", "note", "pinned"}
    if unknown:
        raise ValueError(f"Unbekanntes Feld: {sorted(unknown)[0]}")
    title = body.get("title") or ""
    note = body.get("note") or ""
    tags = body.get("tags") or []
    pinned = body.get("pinned", False)
    if not isinstance(title, str) or len(title) > MAX_TITLE or re.search(r"[\x00-\x1f\x7f]", title):
        raise ValueError(f"Titel: höchstens {MAX_TITLE} Zeichen, eine Zeile.")
    if not isinstance(note, str) or len(note) > MAX_NOTE or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", note):
        raise ValueError(f"Notiz: höchstens {MAX_NOTE} Zeichen.")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("Tags: Liste von Wörtern.")
    seen = []
    for t in (t.strip().lower() for t in tags):
        if t and t not in seen:
            seen.append(t)
    if len(seen) > MAX_TAGS or not all(TAG_RE.match(t) for t in seen):
        raise ValueError(f"Tags: höchstens {MAX_TAGS}, je bis 24 Zeichen aus Buchstaben, Ziffern, Punkt, Strich.")
    if not isinstance(pinned, bool):
        raise ValueError("pinned: ja oder nein.")
    return {"title": title.strip() or None, "tags": seen, "note": note.strip(), "pinned": pinned}


def write_notes(path, notes):
    notes = {**notes, "updated": dt.datetime.now().isoformat(timespec="seconds")}
    tmp = os.path.join(path, NOTES_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(path, NOTES_FILE))      # atomar: nie eine halbe Datei
    return notes


def empty_trash(root):
    """Räumt Läufe aus dem Papierkorb, die älter als TRASH_DAYS sind (beim Start und nach jedem Löschen)."""
    trash = os.path.join(root, TRASH_DIR)
    if not os.path.isdir(trash):
        return
    cutoff = time.time() - TRASH_DAYS * 86400
    for name in os.listdir(trash):
        p = os.path.join(trash, name)
        try:
            if os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def rederive(s):
    """Abgeleitete Kennzahlen frisch rechnen – auch Läufe aus älteren Versionen bekommen so die aktuelle
    Bewertung. Website-Tests prüfen die Messqualität erst am Ende – vorher bleibt sie weg."""
    if s.get("config", {}).get("kind") in ("web", "api", "flow"):
        if s.get("quality"):
            s["quality"] = ws.assess_quality(s)
        s["capacity"], s["verdict"] = ws.capacity(s), ws.verdict(s)
    else:
        s["quality"] = lt.assess_quality(s)
        s["capacity"], s["economics"], s["verdict"] = lt.capacity(s), lt.economics(s), lt.verdict(s)
    return s


def run_row(root, name):
    """Eine Zeile der Lauf-Liste: Stammdaten, Notizen und die Kennzahlen für den Verlauf."""
    path = os.path.join(root, name)
    sfile = os.path.join(path, "summary.json")
    if not (RUN_NAME_RE.match(name) and os.path.isfile(sfile)):
        return None
    try:
        with open(sfile, encoding="utf-8") as f:
            s = rederive(json.load(f))
    except Exception:
        return None
    cfg, kind = s.get("config") or {}, (s.get("config") or {}).get("kind") or "llm"
    base = s.get("baseline") or {}
    cap = s.get("capacity") or {}
    return {"name": name, "kind": kind, "model": cfg.get("model"), "base_url": cfg.get("base_url"),
            "started": (s.get("meta") or {}).get("started"),
            "tests": [k for k in ("baseline", "ramp", "rate", "context", "spike", "soak") if k in s],
            "report": os.path.isfile(os.path.join(path, REPORT_NAME)),
            "pdf": os.path.isfile(os.path.join(path, PDF_NAME)),
            # für den Verlauf über mehrere Läufe
            "users": cap.get("users"), "target_users": cfg.get("target_users") or 0,
            "status": (s.get("verdict") or {}).get("status"),
            "alone": base.get("e2e_p50") if kind in ("web", "api", "flow") else base.get("ttft_p50"),
            "version": (s.get("meta") or {}).get("version"),
            **read_notes(path)}


@routes.get("/api/runs")
async def runs(req):
    root = req.app["runner"].root
    try:
        limit = max(1, min(int(req.query.get("limit", 50)), 500))
    except ValueError:
        limit = 50
    rows = [r for r in (run_row(root, n) for n in sorted(os.listdir(root), reverse=True)) if r]
    rows.sort(key=lambda r: (not r["pinned"], r["name"]), reverse=False)
    rows.sort(key=lambda r: r["pinned"], reverse=True)
    return web.json_response({"runs": rows[:limit]})


@routes.put("/api/runs/{name}/notes")
async def put_notes(req):
    _, path = _run_dir(req)
    if not os.path.isfile(os.path.join(path, "summary.json")):
        raise web.HTTPNotFound()
    try:
        notes = clean_notes(await req.json())
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response(write_notes(path, notes))


@routes.delete("/api/runs/{name}")
async def delete_run(req):
    """Verschiebt den Lauf in den Papierkorb (results/.papierkorb); endgültig weg nach TRASH_DAYS Tagen."""
    name, path = _run_dir(req)
    runner = req.app["runner"]
    root = os.path.realpath(runner.root)
    # Nur echte Ordner direkt unterhalb des Ergebnisordners – kein Symlink nach draußen
    if os.path.islink(path) or os.path.dirname(os.path.realpath(path)) != root:
        raise web.HTTPNotFound()
    if runner.running and os.path.realpath(runner.outdir or "") == os.path.realpath(path):
        return web.json_response({"error": "Dieser Lauf läuft gerade – erst abbrechen, dann löschen."}, status=409)
    trash = os.path.join(runner.root, TRASH_DIR)
    os.makedirs(trash, exist_ok=True)
    target = os.path.join(trash, f"{name}_{dt.datetime.now():%Y%m%d_%H%M%S}")
    shutil.move(path, target)
    os.utime(target, None)
    empty_trash(runner.root)
    return web.json_response({"ok": True, "trash_days": TRASH_DAYS})


@routes.get("/api/runs/{name}/summary.json")
async def run_summary(req):
    _, path = _run_dir(req)
    with open(os.path.join(path, "summary.json"), encoding="utf-8") as f:
        s = rederive(json.load(f))
    return web.json_response(s, dumps=lambda o: json.dumps(o, default=str))


@routes.get("/api/runs/{name}/report.pptx")
async def run_report(req):
    name, path = _run_dir(req)
    f = os.path.join(path, REPORT_NAME)
    if not os.path.isfile(f):
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={
        "Content-Disposition": f'attachment; filename="{report_filename(path, name, "pptx")}"'})


@routes.get("/api/runs/{name}/report.pdf")
async def run_pdf(req):
    name, path = _run_dir(req)
    f = os.path.join(path, PDF_NAME)
    if not os.path.isfile(f):
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={
        "Content-Disposition": f'attachment; filename="{report_filename(path, name, "pdf")}"'})


@routes.get("/api/compare")
async def compare(req):
    """Vergleichsbericht aus zwei oder mehr früheren Läufen (?runs=a,b[,c])."""
    root = req.app["runner"].root
    names = [n for n in req.query.get("runs", "").split(",") if n]
    if len(names) < 2 or not all(RUN_NAME_RE.match(n) and os.path.isfile(os.path.join(root, n, "summary.json"))
                                 for n in names):
        return web.json_response({"error": "Bitte mindestens zwei vorhandene Läufe wählen."}, status=400)
    names.sort()  # ältester Lauf = Referenz
    try:
        build = comparison_builder([run_kind(os.path.join(root, n)) for n in names])
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    out = os.path.join(root, f"Vergleich_{dt.datetime.now():%Y%m%d_%H%M%S}.pptx")
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, build, [os.path.join(root, n) for n in names], out, None)
    except Exception as e:  # noqa
        return web.json_response({"error": f"Vergleich fehlgeschlagen: {e}"}, status=500)
    return web.FileResponse(out, headers={
        "Content-Disposition": f'attachment; filename="{os.path.basename(out)}"'})


@routes.get(r"/api/runs/{name}/{shot:schritt_(\d\d|fehler)\.png}")
async def run_screenshot(req):
    """Bildschirmfotos der Aufzeichnung eines Ablaufs."""
    _, path = _run_dir(req)
    f = os.path.join(path, req.match_info["shot"])
    if not os.path.isfile(f):
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "no-store"})


@routes.get("/api/runs/{name}/raw_requests.jsonl")
async def run_raw(req):
    name, path = _run_dir(req)
    return web.FileResponse(os.path.join(path, "raw_requests.jsonl"), headers={
        "Content-Disposition": f'attachment; filename="raw_{name[8:]}.jsonl"'})


TOKEN_HEADER = "X-Last-Token"


def token_guard(token):
    """In der Desktop-App läuft das Backend auf dem eigenen Rechner an einem freien Port. Andere Programme und
    Webseiten im Browser könnten es dort erreichen – deshalb antwortet es nur mit dem Schlüssel, den die App beim
    Start erzeugt und der Oberfläche mitgibt."""
    @web.middleware
    async def guard(req, handler):
        if not hmac.compare_digest(req.headers.get(TOKEN_HEADER, ""), token):
            return web.json_response({"error": "Kein Zugriff."}, status=403)
        return await handler(req)
    return guard


def make_app(results_root, token=None):
    os.makedirs(results_root, exist_ok=True)
    empty_trash(results_root)
    app = web.Application(middlewares=[token_guard(token)] if token else [])
    app["runner"] = Runner(results_root)
    app["live"] = LiveSlot()
    app.add_routes(routes)

    async def start_reaper(app):
        app["live_reaper"] = asyncio.create_task(_live_reaper(app))

    async def stop_live(app):
        app["live_reaper"].cancel()
        await close_live(app)

    app.on_startup.append(start_reaper)
    app.on_cleanup.append(stop_live)
    return app


def main():
    ap = argparse.ArgumentParser(description="Weboberfläche für den LLM-Härtetest")
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 = aus dem Netzwerk erreichbar (ohne Passwortschutz!)")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--results", default=os.path.join(HERE, "results"),
                    help="Ordner für alle Testläufe")
    a = ap.parse_args()
    app = make_app(a.results, os.environ.get("LAST_BACKEND_TOKEN") or None)
    shown = "localhost" if a.host in ("127.0.0.1", "0.0.0.0") else a.host
    print(f"\n  LLM-Härtetest läuft auf  http://{shown}:{a.port}\n"
          f"  Ergebnisse werden gespeichert in {a.results}\n")
    web.run_app(app, host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
