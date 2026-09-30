#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import json
import os
import re
import sys

try:
    from aiohttp import web, ClientSession, ClientTimeout
    import pptx  # noqa: F401  (für den Bericht)
except ImportError:
    exe = sys.executable if " " not in sys.executable else f'"{sys.executable}"'
    sys.exit("Es fehlen Python-Pakete für genau dieses Python (" + sys.executable + ").\n"
             "Installieren mit:\n    " + exe + " -m pip install aiohttp python-pptx reportlab")

import llm_stresstest as lt

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_NAME = "LLM-Haertetest.pptx"
PDF_NAME = "LLM-Haertetest.pdf"
RUN_NAME_RE = re.compile(r"^results_[\w-]+$")


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
        self.st = lt.StressTest(a, self.outdir)
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
                try:
                    lt.log("Erstelle PowerPoint-Bericht …")
                    await asyncio.get_running_loop().run_in_executor(
                        None, lt.build_report, s, path, self.args)
                    self.report = path
                    lt.log("✓ Bericht fertig.")
                    pdf = await asyncio.get_running_loop().run_in_executor(
                        None, lt.build_pdf_report, s, os.path.join(self.outdir, PDF_NAME))
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

def build_args(cfg):
    """JSON aus dem Formular → argparse-Namespace mit denselben Defaults wie die CLI."""
    p = lt.build_parser()
    a = p.parse_args([])
    blocked = {"report_only", "out", "quick"}
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
            raise ValueError(f"Ungültiger Wert für {key}: {val!r}")
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
            raise ValueError("„Wie viele Fragen pro Minute?“: Zahlen mit Komma oder auto")
    return a


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
    return web.json_response({"defaults": a, "quick": lt.QUICK_PROFILE})


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
        a = build_args(await req.json())
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    name = runner.start(a)
    return web.json_response({"ok": True, "run": name})


@routes.post("/api/stop")
async def stop(req):
    req.app["runner"].stop()
    return web.json_response({"ok": True})


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


@routes.get("/api/runs")
async def runs(req):
    root = req.app["runner"].root
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, name)
        sfile = os.path.join(path, "summary.json")
        if not (RUN_NAME_RE.match(name) and os.path.isfile(sfile)):
            continue
        try:
            with open(sfile) as f:
                s = json.load(f)
        except Exception:
            continue
        out.append({"name": name, "model": s.get("config", {}).get("model"),
                    "base_url": s.get("config", {}).get("base_url"),
                    "started": s.get("meta", {}).get("started"),
                    "tests": [k for k in ("baseline", "ramp", "rate", "context", "spike", "soak") if k in s],
                    "report": os.path.isfile(os.path.join(path, REPORT_NAME)),
                    "pdf": os.path.isfile(os.path.join(path, PDF_NAME))})
    return web.json_response({"runs": out[:50]})


@routes.get("/api/runs/{name}/summary.json")
async def run_summary(req):
    _, path = _run_dir(req)
    with open(os.path.join(path, "summary.json"), encoding="utf-8") as f:
        s = json.load(f)
    # Abgeleitete Kennzahlen immer frisch rechnen – auch für Läufe aus älteren Versionen
    s.setdefault("quality", lt.assess_quality(s))
    s["capacity"], s["economics"], s["verdict"] = lt.capacity(s), lt.economics(s), lt.verdict(s)
    return web.json_response(s, dumps=lambda o: json.dumps(o, default=str))


@routes.get("/api/runs/{name}/report.pptx")
async def run_report(req):
    name, path = _run_dir(req)
    f = os.path.join(path, REPORT_NAME)
    if not os.path.isfile(f):
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={
        "Content-Disposition": f'attachment; filename="LLM-Haertetest_{name[8:]}.pptx"'})


@routes.get("/api/runs/{name}/report.pdf")
async def run_pdf(req):
    name, path = _run_dir(req)
    f = os.path.join(path, PDF_NAME)
    if not os.path.isfile(f):
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={
        "Content-Disposition": f'attachment; filename="LLM-Haertetest_{name[8:]}.pdf"'})


@routes.get("/api/compare")
async def compare(req):
    """Vergleichsbericht aus zwei oder mehr früheren Läufen (?runs=a,b[,c])."""
    root = req.app["runner"].root
    names = [n for n in req.query.get("runs", "").split(",") if n]
    if len(names) < 2 or not all(RUN_NAME_RE.match(n) and os.path.isfile(os.path.join(root, n, "summary.json"))
                                 for n in names):
        return web.json_response({"error": "Bitte mindestens zwei vorhandene Läufe wählen."}, status=400)
    names.sort()  # ältester Lauf = Referenz
    out = os.path.join(root, f"Vergleich_{dt.datetime.now():%Y%m%d_%H%M%S}.pptx")
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lt.build_comparison, [os.path.join(root, n) for n in names], out, None)
    except Exception as e:  # noqa
        return web.json_response({"error": f"Vergleich fehlgeschlagen: {e}"}, status=500)
    return web.FileResponse(out, headers={
        "Content-Disposition": f'attachment; filename="{os.path.basename(out)}"'})


@routes.get("/api/runs/{name}/raw_requests.jsonl")
async def run_raw(req):
    name, path = _run_dir(req)
    return web.FileResponse(os.path.join(path, "raw_requests.jsonl"), headers={
        "Content-Disposition": f'attachment; filename="raw_{name[8:]}.jsonl"'})


def main():
    ap = argparse.ArgumentParser(description="Weboberfläche für den LLM-Härtetest")
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 = aus dem Netzwerk erreichbar (ohne Passwortschutz!)")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--results", default=os.path.join(HERE, "results"),
                    help="Ordner für alle Testläufe")
    a = ap.parse_args()
    os.makedirs(a.results, exist_ok=True)
    app = web.Application()
    app["runner"] = Runner(a.results)
    app.add_routes(routes)
    shown = "localhost" if a.host in ("127.0.0.1", "0.0.0.0") else a.host
    print(f"\n  LLM-Härtetest läuft auf  http://{shown}:{a.port}\n"
          f"  Ergebnisse werden gespeichert in {a.results}\n")
    web.run_app(app, host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
