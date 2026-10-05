# -*- coding: utf-8 -*-
"""
Aufzeichnen eines Ablaufs mit einem echten, unsichtbaren Browser (Playwright/Chromium).

Führt die Schritte aus flow_stresstest.parse_steps aus, macht pro Schritt ein Bildschirmfoto in den
Ergebnisordner und schneidet ab „messen ab hier“ alle Anfragen an Server mit. Das Ergebnis ist ein
Plan für flow_stresstest.FlowClient – er bleibt im Arbeitsspeicher, weil er Sitzungs-Cookies enthält.
"""

import asyncio
import os
import re
import time

import llm_stresstest as lt
from llm_stresstest import log
from flow_stresstest import (MAX_RESPONSE, RECORD_TYPES, STEP_TIMEOUT_MS, build_plan, fill_text,
                             is_selector, public_plan)

LONG_WAIT_MS = 180_000       # eine Chat-Antwort darf dauern
TEXT_TYPES = ("application/json", "text/", "application/x-ndjson", "application/problem+json")


def describe(step):
    """Der Schritt in Worten – Platzhalter bleiben Platzhalter, damit nichts Geheimes ins Protokoll kommt."""
    k = step["kind"]
    if k == "open":
        return f"öffne {step['url']}"
    if k == "fill":
        return f"tippe in „{step['target']}“ {step['text']}"
    if k == "click":
        return f"klicke „{step['target']}“"
    if k == "press":
        return f"drücke {step['key']}"
    if k == "wait_text":
        return f"warte auf Text „{step['target']}“"
    if k == "wait_sel":
        return f"warte auf „{step['target']}“"
    if k == "wait_s":
        return f"warte {lt.fmt(step['seconds'], 0)} s"
    if k == "wait_first":
        return f"warte auf erste Antwort in „{step['target']}“"
    if k == "wait_done":
        return f"warte bis „{step['target']}“ fertig ist"
    return "messen ab hier"


def _short_error(err):
    text = str(err).splitlines()[0] if str(err) else type(err).__name__
    text = re.sub(r"\s+", " ", text)
    if "Timeout" in type(err).__name__ or "Timeout" in text:
        return "nichts gefunden oder nicht passiert (Zeitüberschreitung)"
    return text[:160]


async def _locator(page, target, prefer="any"):
    """Feld, Knopf oder Element – per Selektor oder so, wie ein Mensch es sieht.
    Kandidaten in sinnvoller Reihenfolge: zum Tippen zuerst Felder, zum Klicken zuerst Knöpfe;
    sichtbarer Text kommt zuletzt, damit nicht eine Überschrift statt des Knopfes getroffen wird."""
    if is_selector(target):
        return page.locator(target).first
    fields = [page.get_by_label(target), page.get_by_placeholder(target), page.get_by_role("textbox", name=target)]
    buttons = [page.get_by_role("button", name=target), page.get_by_role("link", name=target)]
    order = {"fill": fields + buttons, "click": buttons + fields}.get(prefer, fields + buttons)
    for loc in order + [page.get_by_text(target, exact=True), page.get_by_text(target)]:
        if await loc.count():
            return loc.first
    return page.get_by_text(target).first


async def _wait_done(loc, quiet_s):
    """Fertig, wenn sich der Text so lange nicht mehr geändert hat (Chat-Antwort zu Ende)."""
    await loc.wait_for(timeout=LONG_WAIT_MS)
    last, since, deadline = None, time.perf_counter(), time.perf_counter() + LONG_WAIT_MS / 1000
    while time.perf_counter() < deadline:
        text = await loc.inner_text()
        if text != last:
            last, since = text, time.perf_counter()
        elif text.strip() and time.perf_counter() - since >= quiet_s:
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("Antwort hört nicht auf, sich zu ändern")


async def _run_step(page, step, secrets, state):
    k = step["kind"]
    if k == "open":
        await page.goto(step["url"], wait_until="domcontentloaded")
    elif k == "fill":
        await (await _locator(page, step["target"], "fill")).fill(fill_text(step["text"], secrets))
    elif k == "click":
        await (await _locator(page, step["target"], "click")).click()
    elif k == "press":
        await page.keyboard.press(step["key"])
    elif k == "wait_text":
        await page.get_by_text(step["target"]).first.wait_for()
    elif k == "wait_sel":
        await (await _locator(page, step["target"])).wait_for()
    elif k == "wait_s":
        await page.wait_for_timeout(step["seconds"] * 1000)
    elif k == "measure":
        state["measuring"] = True
        state["t_measure"] = time.perf_counter()
    elif k == "wait_first":
        loc = await _locator(page, step["target"])
        await loc.filter(has_text=re.compile(r"\S")).wait_for(timeout=LONG_WAIT_MS)
    elif k == "wait_done":
        await _wait_done(await _locator(page, step["target"]), step["quiet"])


async def record(args, outdir):
    """Spielt die Schritte ab und liefert (Plan, Vorab-Infos). Wirft PreflightError mit Zeilennummer."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise lt.PreflightError("Für Abläufe wird ein Browser gebraucht (Playwright). Im Docker-Image ist er "
                                "enthalten; sonst: python -m pip install playwright && playwright install chromium")
    steps, secrets = args.steps, args.secrets
    state = {"measuring": False, "ws": False, "t_measure": None}
    pending, records, shots = {}, [], []

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)

        def on_request(req):
            if state["measuring"] and req.resource_type in RECORD_TYPES and req.url.startswith("http"):
                pending[req] = {"t_start": time.perf_counter()}

        def on_response(resp):
            entry = pending.get(resp.request)
            if entry is not None:
                entry["t_headers"] = time.perf_counter()

        async def finished(req):
            entry = pending.get(req)
            if entry is None:
                return
            entry["t_end"] = time.perf_counter()
            try:
                resp = await req.response()
                headers = await req.all_headers()
                resp_headers = await resp.all_headers() if resp else {}
                ctype = (resp_headers.get("content-type") or "").lower()
                body = None
                if resp and any(ctype.startswith(t) for t in TEXT_TYPES):
                    raw = await resp.body()
                    body = raw[:MAX_RESPONSE].decode("utf-8", "replace")
                size = len(await resp.body()) if resp else 0
            except Exception:                                   # Antwort nicht mehr lesbar – dann ohne Inhalt
                resp, headers, resp_headers, ctype, body, size = None, {}, {}, "", None, 0
            records.append({
                "i": len(records), "method": req.method, "url": req.url, "headers": headers,
                "body": req.post_data, "status": resp.status if resp else 0, "resp_headers": resp_headers,
                "resp_body": body, "bytes": size, "resource_type": req.resource_type,
                "stream": ctype.startswith("text/event-stream") or ctype.startswith("application/x-ndjson")
                or (entry["t_end"] - entry.get("t_headers", entry["t_end"]) > 1.0),
                **{k: v for k, v in entry.items()},
            })

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfinished", lambda req: asyncio.ensure_future(finished(req)))
        page.on("websocket", lambda ws: state.update(ws=True) if state["measuring"] else None)

        try:
            for n, step in enumerate(steps, start=1):
                t = time.perf_counter()
                try:
                    await _run_step(page, step, secrets, state)
                except Exception as err:                        # noqa – jeder Fehler wird erklärt und bebildert
                    shot = "schritt_fehler.png"
                    try:
                        await page.screenshot(path=os.path.join(outdir, shot))
                    except Exception:
                        shot = None
                    raise lt.PreflightError(
                        f"Schritt in Zeile {step['line']} („{describe(step)}“) hat nicht geklappt: "
                        f"{_short_error(err)}." + (" Bildschirmfoto: schritt_fehler.png" if shot else ""))
                shot = f"schritt_{n:02d}.png"
                try:
                    await page.screenshot(path=os.path.join(outdir, shot))
                except Exception:
                    shot = None
                shots.append({"line": step["line"], "text": describe(step), "screenshot": shot,
                              "ms": (time.perf_counter() - t) * 1000})
                log(f"  ✓ {describe(step)}")
            await page.wait_for_timeout(800)                    # Nachzügler
            if pending:
                for _ in range(20):                             # offene Anfragen zu Ende kommen lassen
                    if len(records) >= len(pending):
                        break
                    await page.wait_for_timeout(250)
            cookies = await context.cookies()
            final_url = page.url
        finally:
            await browser.close()

    if state["ws"]:
        raise lt.PreflightError("Im Messbereich benutzt die Seite eine Dauerverbindung (WebSocket). Die lässt "
                                "sich nicht ohne Browser abspielen – dieser Ablauf geht so nicht.")
    if not records:
        raise lt.PreflightError("Im Messbereich hat die Seite keine Anfragen an einen Server geschickt. "
                                "Steht „messen ab hier“ an der richtigen Stelle?")
    records.sort(key=lambda r: r["t_start"])
    for i, r in enumerate(records):
        r["i"] = i
    plan = build_plan(records)
    plan["cookies"] = [{"name": c["name"], "value": c["value"], "domain": c.get("domain", ""),
                        "path": c.get("path", "/"), "secure": bool(c.get("secure"))} for c in cookies]
    main = records[plan["main"]]
    info = {"status": main["status"], "bytes": main.get("bytes", 0), "assets": len(records), "files": [],
            "total_bytes": sum(r.get("bytes", 0) for r in records), "final_url": final_url, "busy": None,
            "rtt_ms": (main.get("t_headers", main["t_end"]) - main["t_start"]) * 1000,
            "requests": public_plan(plan), "main": plan["main"], "steps": shots,
            "measured_ms": (records[-1]["t_end"] - state["t_measure"]) * 1000 if state["t_measure"] else None}
    return plan, info
