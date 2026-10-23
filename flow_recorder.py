"""
Aufzeichnen eines Ablaufs mit einem echten, unsichtbaren Browser (Playwright/Chromium).

Führt die Schritte aus flow_stresstest.parse_steps aus, macht pro Schritt ein Bildschirmfoto in den
Ergebnisordner und schneidet ab „messen ab hier“ alle Anfragen an Server mit. Das Ergebnis ist ein
Plan für flow_stresstest.FlowClient – er bleibt im Arbeitsspeicher, weil er Sitzungs-Cookies enthält.
"""

import asyncio
import base64
import os
import re
import time
import weakref

import llm_stresstest as lt
from flow_stresstest import (
    AUTH_NEEDED,
    MAX_RESPONSE,
    RECORD_TYPES,
    STEP_TIMEOUT_MS,
    basic_header,
    browser_credentials,
    build_plan,
    fill_text,
    is_selector,
    public_plan,
)
from llm_stresstest import log

LONG_WAIT_MS = 180_000       # eine Chat-Antwort darf dauern
PARALLEL_RECORDINGS = 3      # so viele Konten werden gleichzeitig aufgezeichnet (je ein Browser-Fenster)
TEXT_TYPES = ("application/json", "text/", "application/x-ndjson", "application/problem+json")
VIEWPORT = {"width": 1280, "height": 800}
SCAN_ELEMENTS = 80           # so viele Felder und Knöpfe bekommen beim Vorführen eine klickbare Fläche


def _where_words(step):
    return (f" bei „{step['near']}“" if step.get("near") else "") + (f" (Nr. {step['nth']})" if step.get("nth") else "")


def describe(step):
    """Der Schritt in Worten – Platzhalter bleiben Platzhalter, damit nichts Geheimes ins Protokoll kommt."""
    k = step["kind"]
    if k == "open":
        return f"öffne {step['url']}"
    if k == "fill":
        return f"tippe in „{step['target']}“{_where_words(step)} {step['text']}"
    if k == "click":
        return f"klicke „{step['target']}“{_where_words(step)}"
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
    if k == "wait_quiet":
        return "warte bis die Seite ruhig ist"
    return "messen ab hier"


def _short_error(err):
    text = str(err).splitlines()[0] if str(err) else type(err).__name__
    text = re.sub(r"\s+", " ", text)
    if "Timeout" in type(err).__name__ or "Timeout" in text:
        return "nichts gefunden oder nicht passiert (Zeitüberschreitung)"
    return text[:160]


def _candidates(page, target, prefer):
    """Suchen in sinnvoller Reihenfolge: genaue Beschriftung vor „enthält“, zum Tippen zuerst Felder,
    zum Klicken zuerst Knöpfe; sichtbarer Text zuletzt, damit nicht eine Überschrift statt des Knopfes zählt."""
    if is_selector(target):
        return [page.locator(target)]
    if prefer == "text":
        return [page.get_by_text(target)]

    def fields(exact):
        return [page.get_by_label(target, exact=exact), page.get_by_placeholder(target, exact=exact),
                page.get_by_role("textbox", name=target, exact=exact)]

    def buttons(exact):
        return [page.get_by_role("button", name=target, exact=exact), page.get_by_role("link", name=target, exact=exact)]

    first, second = (buttons, fields) if prefer == "click" else (fields, buttons)
    return (first(True) + second(True) + first(False) + second(False)
            + [page.get_by_text(target, exact=True), page.get_by_text(target)])


def _frames(page):
    """Die Seite zuerst, dann eingebettete Frames (Login-Fenster, Cookie-Banner)."""
    return [page.main_frame] + [f for f in page.frames if f is not page.main_frame and not f.is_detached()]


async def _matches(page, target, prefer="any", wait_ms=STEP_TIMEOUT_MS):
    """Alle sichtbaren Treffer der ersten Suche, die etwas findet. Wartet, bis etwas erscheint – nach einem
    Klick lädt die nächste Seite oft noch; so braucht es kaum eigene Warte-Schritte. Jede Art der Suche
    läuft erst auf der Seite, dann in ihren Frames; Shadow DOM durchsuchen Playwrights Locatoren von selbst."""
    deadline = time.perf_counter() + wait_ms / 1000
    while True:
        per_frame = [_candidates(f, target, prefer) for f in _frames(page)]
        for loc in (c for group in zip(*per_frame) for c in group):
            loc = loc.filter(visible=True)
            n = await loc.count()
            if n:
                return loc, n
        if time.perf_counter() >= deadline:
            raise TimeoutError(f"„{target}“ ist nicht auf der Seite")
        await asyncio.sleep(0.25)


# „bei …“: Für jeden Treffer der engste Bereich um ihn, der den Text enthält. Er zählt nur, wenn in diesem
# Bereich kein anderer Treffer liegt – so meint „Löschen bei Bestellung 4711“ den Knopf in dieser Zeile.
_NEAR_JS = """(els, ctx) => els.map((el) => {
  let n = el;
  while (n && !(n.innerText || "").includes(ctx)) n = n.parentElement;
  return !!n && !els.some((o) => o !== el && n.contains(o));
})"""
_MAX_MATCHES = 50


async def _near(loc, n, near):
    """Treffer, die zum Text „bei …“ gehören (Indizes in Lesereihenfolge)."""
    if n > _MAX_MATCHES:
        return []
    return [i for i, ok in enumerate(await loc.evaluate_all(_NEAR_JS, near)) if ok]


async def _locator(page, target, prefer="any", near=None, nth=None, wait_ms=STEP_TIMEOUT_MS):
    """Das gemeinte Element. Gibt es mehrere: „bei …“ wählt das nächste am Text, „Nr. …“ zählt in Lesereihenfolge."""
    loc, n = await _matches(page, target, prefer, wait_ms)
    if near:
        idx = await _near(loc, n, near)
        if not idx:
            raise ValueError(f"„{target}“ gibt es, aber nicht bei „{near}“")
        if (nth or 1) > len(idx):
            raise ValueError(f"„{target}“ bei „{near}“ gibt es nur {len(idx)}-mal")
        return loc.nth(idx[(nth or 1) - 1])
    if nth:
        if nth > n:
            raise ValueError(f"„{target}“ gibt es nur {n}-mal, nicht {nth}-mal")
        return loc.nth(nth - 1)
    return loc.first


async def _settle(page):
    """Nach Klick oder Taste: Lädt eine neue Seite, abwarten; dann, bis das Netz kurz ruhig ist (höchstens 3 s)."""
    await page.wait_for_timeout(200)
    for state, ms in (("load", 10_000), ("networkidle", 3000)):
        try:
            await page.wait_for_load_state(state, timeout=ms)
        except Exception:                                   # noqa – Seiten mit Dauerverbindung werden nie ruhig
            pass


async def _wait_done(loc, quiet_s, wait_ms=LONG_WAIT_MS):
    """Fertig, wenn sich der Text so lange nicht mehr geändert hat (Chat-Antwort zu Ende)."""
    await loc.wait_for(timeout=wait_ms)
    last, since, deadline = None, time.perf_counter(), time.perf_counter() + wait_ms / 1000
    while time.perf_counter() < deadline:
        text = await loc.inner_text()
        if text != last:
            last, since = text, time.perf_counter()
        elif text.strip() and time.perf_counter() - since >= quiet_s:
            return
        await asyncio.sleep(0.25)
    raise TimeoutError("Die Seite hört nicht auf, sich zu ändern")


# ════════════════════════════════════════════════════════════════════════════
#  Was hat die letzte Aktion angestoßen? (Chat-Anfrage, gestreamte Antwort …)
# ════════════════════════════════════════════════════════════════════════════

ACTIVITY_TYPES = {"xhr", "fetch", "eventsource", "document"}
OPEN_STREAM_QUIET_S = 20     # bleibt eine Verbindung offen, gilt die Seite nach so langem Stillstand als fertig


class _Activity:
    """Offene Anfragen einer Seite mit Startzeit. mark() bei jeder Aktion: Gewartet wird nur auf das, was danach
    begann – eine Dauerverbindung, die die Seite schon beim Laden geöffnet hat, hält nichts auf."""

    def __init__(self, page):
        self.inflight, self.since = {}, time.perf_counter()
        page.on("request", self._start)
        page.on("requestfinished", self._done)
        page.on("requestfailed", self._done)
        page.on("response", self._response)
        page.on("framenavigated", self._navigated)

    def _start(self, req):
        if req.resource_type in ACTIVITY_TYPES:
            self.inflight[req] = time.perf_counter()

    def _done(self, req):
        self.inflight.pop(req, None)

    def _navigated(self, frame):
        # Neues Dokument im Frame: Anfragen des alten melden nie mehr „fertig“ (z. B. ein fetch, dessen Antwort
        # nach dem Seitenwechsel keiner mehr liest) – sie zählen nicht mehr
        for req in list(self.inflight):
            try:
                if req.frame == frame and not req.is_navigation_request():
                    self._done(req)
            except Exception:                               # noqa – Frame schon weg
                self._done(req)

    def _response(self, resp):
        # Eine Weiterleitung meldet nie „fertig“ – weiter geht es mit einer neuen Anfrage
        if 300 <= resp.status < 400:
            self._done(resp.request)

    def mark(self):
        self.since = time.perf_counter()

    def pending(self):
        return [r for r, t in self.inflight.items() if t >= self.since]


_ACTIVITY = weakref.WeakKeyDictionary()


def activity(page):
    """Der Tracker der Seite – früh anlegen (gleich nach new_page), sonst fehlen die ersten Anfragen."""
    if page not in _ACTIVITY:
        _ACTIVITY[page] = _Activity(page)
    return _ACTIVITY[page]


async def _wait_settled(page, quiet_s, wait_ms=LONG_WAIT_MS):
    """Ruhig heißt: Alle Anfragen seit der letzten Aktion sind fertig und der Text steht quiet_s lang still.
    Eine KI, die erst nachdenkt, hält ihre Anfrage offen – so wird auf die ganze Antwort gewartet."""
    act = activity(page)
    deadline = time.perf_counter() + wait_ms / 1000
    last, since, changed = await page_text(page), time.perf_counter(), False
    while True:
        await asyncio.sleep(0.25)
        text, now = await page_text(page), time.perf_counter()
        if text != last:
            last, since, changed = text, now, True
        still = now - since
        if still >= quiet_s and not act.pending():
            return
        if changed and still >= max(quiet_s, OPEN_STREAM_QUIET_S):
            return
        if now >= deadline:
            raise TimeoutError("Die Seite wird nicht fertig")


async def _run_step(page, step, secrets, state):
    k = step["kind"]
    where = {"near": step.get("near"), "nth": step.get("nth")}
    if k in ("fill", "click", "press"):
        activity(page).mark()
    if k == "open":
        resp = await page.goto(step["url"], wait_until="domcontentloaded")
        if resp is not None and resp.status == 401:
            raise PermissionError(AUTH_NEEDED)
        await _settle(page)                                 # Single-Page-Apps sind hier noch leer (weiß)
    elif k == "fill":
        await (await _locator(page, step["target"], "fill", **where)).fill(fill_text(step["text"], secrets))
    elif k == "click":
        await (await _locator(page, step["target"], "click", **where)).click()
        await _settle(page)
    elif k == "press":
        await page.keyboard.press(step["key"])
        await _settle(page)
    elif k == "wait_text":
        await (await _matches(page, step["target"], "text"))[0].first.wait_for()
    elif k == "wait_sel":
        await (await _locator(page, step["target"])).wait_for()
    elif k == "wait_s":
        await page.wait_for_timeout(step["seconds"] * 1000)
    elif k == "measure":
        state["measuring"] = True
        state["t_measure"] = time.perf_counter()
    elif k == "wait_first":
        # Bei Selektoren zählt der letzte Treffer: in einem Chat ist das die neueste Antwort
        loc, _ = await _matches(page, step["target"], wait_ms=LONG_WAIT_MS)
        await loc.last.filter(has_text=re.compile(r"\S")).wait_for(timeout=LONG_WAIT_MS)
    elif k == "wait_done":
        loc, _ = await _matches(page, step["target"], wait_ms=LONG_WAIT_MS)
        await _wait_done(loc.last, step["quiet"])
    elif k == "wait_quiet":
        await _wait_settled(page, step["quiet"])


async def record(args, outdir):
    """Spielt die Schritte je Konto ab und liefert ([Plan je Konto], Vorab-Infos). Fotos macht nur das erste
    Konto. Wirft PreflightError mit Zeilennummer (und Konto-Nummer, wenn es mehrere gibt)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise lt.PreflightError("Für Abläufe wird ein Browser gebraucht (Playwright). Im Docker-Image ist er "
                                "enthalten; sonst: python -m pip install playwright && playwright install chromium") from None
    accounts = getattr(args, "accounts", None) or [args.secrets]
    sem = asyncio.Semaphore(PARALLEL_RECORDINGS)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            async def one(i, secrets):
                async with sem:
                    try:
                        return await _record_account(browser, args.steps, secrets, outdir if i == 0 else None,
                                                     quiet=i > 0, site_auth=getattr(args, "site_auth", None))
                    except lt.PreflightError as e:
                        raise lt.PreflightError((f"Konto {i + 1}: " if len(accounts) > 1 else "") + str(e)) from None
            results = await asyncio.gather(*(one(i, s) for i, s in enumerate(accounts)))
        finally:
            await browser.close()
    plans = [plan for plan, _ in results]
    info = results[0][1]
    info["accounts"] = len(plans)
    return plans, info


async def _record_account(browser, steps, secrets, outdir, quiet=False, site_auth=None):
    """Ein Konto, ein eigenes Browser-Fenster (eigene Cookies). outdir=None: keine Bildschirmfotos.
    site_auth: Seitenschutz – der Browser meldet sich damit an; im Plan steht die Kopfzeile dann nicht."""
    state = {"measuring": False, "ws": False, "t_measure": None}
    pending, records, shots = {}, [], []

    context = await browser.new_context(viewport=VIEWPORT, http_credentials=browser_credentials(site_auth, steps[0]["url"]))
    page = await context.new_page()
    activity(page)
    page.set_default_timeout(STEP_TIMEOUT_MS)
    basic = basic_header(site_auth) if site_auth else None

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
            headers = {k: v for k, v in (await req.all_headers()).items()
                       if not (basic and k.lower() == "authorization" and v == basic)}
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
                shot = "schritt_fehler.png" if outdir else None
                if shot:
                    try:
                        await page.screenshot(path=os.path.join(outdir, shot))
                    except Exception:
                        shot = None
                raise lt.PreflightError(
                    f"Schritt in Zeile {step['line']} („{describe(step)}“) hat nicht geklappt: "
                    f"{_short_error(err)}." + (" Bildschirmfoto: schritt_fehler.png" if shot else "")) from err
            shot = f"schritt_{n:02d}.png" if outdir else None
            if shot:
                try:
                    await page.screenshot(path=os.path.join(outdir, shot))
                except Exception:
                    shot = None
            shots.append({"line": step["line"], "text": describe(step), "screenshot": shot,
                          "ms": (time.perf_counter() - t) * 1000})
            if not quiet:
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
        await context.close()

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


# ════════════════════════════════════════════════════════════════════════════
#  Vorführen: was steht auf der Seite, und wie findet ein Schritt ein Element sicher wieder?
# ════════════════════════════════════════════════════════════════════════════

# Läuft in der Seite. Markiert jedes Feld und jeden Knopf mit data-last-scan und meldet, wo er liegt –
# die Oberfläche legt damit klickbare Flächen über das Bildschirmfoto.
# Gemeinsame Helfer: Elemente auch im Shadow DOM finden; Text unmittelbar vor einem Feld (wenn es keine
# Beschriftung hat, steht dort meist, was hinein soll – „Benutzer“, „Kennwort“)
_HELPERS_JS = """
  const deep = (root, sel, out = []) => {
    for (const el of root.querySelectorAll("*")) {
      if (el.matches(sel)) out.push(el);
      if (el.shadowRoot) deep(el.shadowRoot, sel, out);
    }
    return out;
  };
  const clean = (t) => (t || "").replace(/\\s+/g, " ").trim();
  const textBefore = (el) => {
    for (let n = el, depth = 0; n && depth < 3; n = n.parentElement, depth++) {
      for (let s = n.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.matches("input, textarea, select, button")) return "";
        const t = clean(s.innerText);
        if (t) return t.length <= 40 ? t : "";
      }
      const prev = n.previousSibling && n.previousSibling.nodeType === 3 ? clean(n.previousSibling.textContent) : "";
      if (prev) return prev.length <= 40 ? prev : "";
    }
    return "";
  };
"""

# Marken bleiben am Element, solange es lebt – die Vorschau aktualisiert sich laufend, ein Klick auf ein Bild von
# vor einer Sekunde soll trotzdem das richtige Element treffen. Jedes Dokument zählt ab einem zufälligen Start,
# damit eine alte Marke nach einem Seitenwechsel nicht zufällig ein neues Element trifft.
_COLLECT_JS = """([limit, base]) => {""" + _HELPERS_JS + """
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const TEXT_TYPES = ["", "text", "email", "password", "search", "tel", "url", "number"];
  const kindOf = (el) => {
    const tag = el.tagName.toLowerCase(), role = el.getAttribute("role"), type = (el.getAttribute("type") || "").toLowerCase();
    if (tag === "textarea" || el.isContentEditable || role === "textbox" || role === "searchbox") return "field";
    if (tag === "input") {
      if (TEXT_TYPES.includes(type)) return "field";
      if (type === "checkbox" || type === "radio") return "check";
      if (["submit", "button", "reset"].includes(type)) return "button";
      return "";
    }
    if (role === "checkbox" || role === "radio" || role === "switch") return "check";
    if (tag === "a" || role === "link") return "link";
    return "button";
  };
  const vw = innerWidth, vh = innerHeight;
  if (window.__lastScanNext === undefined) window.__lastScanNext = base + Math.floor(Math.random() * 900000);
  const out = [];
  const query = "input, textarea, [contenteditable=''], [contenteditable='true'], [role=textbox], [role=searchbox], " +
    "button, a[href], [role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], [role=radio], [role=switch]";
  for (const el of deep(document, query)) {
    if (out.length >= limit) break;
    if (el.disabled || el.closest("[aria-hidden=true]") || !visible(el)) continue;
    // Ein Feld in einem anderen (contenteditable im Knopf o. Ä.) nur einmal
    if (el.parentElement && el.parentElement.closest("[data-last-scan]")?.matches("button, a[href], [role=button], [role=link]")) continue;
    const kind = kindOf(el);
    if (!kind) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) continue;
    const label = clean(el.getAttribute("aria-label") || (el.labels && el.labels[0] && el.labels[0].innerText) ||
      el.getAttribute("placeholder") || el.innerText || (kind === "field" ? "" : el.value) || el.getAttribute("title") ||
      (kind === "field" ? textBefore(el) : ""));
    let mark = el.getAttribute("data-last-scan");
    if (!mark) {
      mark = String(window.__lastScanNext++);
      el.setAttribute("data-last-scan", mark);
    }
    const x = Math.max(0, r.left), y = Math.max(0, r.top);
    out.push({ mark, kind, label: label.slice(0, 80),
      box: { x, y, w: Math.min(r.right, vw) - x, h: Math.min(r.bottom, vh) - y } });
  }
  return { elements: out, viewport: { w: vw, h: vh } };
}"""

# Für ein markiertes Element: mögliche Namen (so sieht es ein Mensch), Selektoren und Texte in der Nähe
_ABOUT_JS = """([mark, nameMax]) => {""" + _HELPERS_JS + """
  const el = deep(document, `[data-last-scan="${mark}"]`)[0];
  if (!el) return null;
  const usable = (t) => (t && t.length <= nameMax && !t.includes('"') ? t : "");
  const labelOf = (e) => {
    if (e.labels && e.labels.length) return clean([...e.labels].map((l) => l.innerText).join(" "));
    const by = e.getAttribute("aria-labelledby");
    const root = e.getRootNode();
    return by ? clean(by.split(/\\s+/).map((id) => (root.getElementById ? root.getElementById(id) || {} : {}).innerText || "").join(" ")) : "";
  };
  const tag = el.tagName.toLowerCase(), type = (el.getAttribute("type") || "").toLowerCase();
  const field = tag === "textarea" || el.isContentEditable || ["textbox", "searchbox"].includes(el.getAttribute("role")) ||
    (tag === "input" && ["", "text", "email", "password", "search", "tel", "url", "number"].includes(type));
  // Bei Feldern ist der Inhalt das Getippte (womöglich ein Passwort) – nie ein Name
  const own = field ? "" : clean(el.innerText || el.value);
  // Kacheln und Karten: der ganze Text ist zu lang – die erste Zeile (meist die Überschrift) findet sie auch
  const firstLine = field ? "" : clean((el.innerText || "").split("\\n").find((t) => t.trim()) || "");
  const svgTitle = clean((el.querySelector("svg title") || {}).textContent);
  const names = (field
    ? [labelOf(el), el.getAttribute("placeholder"), el.getAttribute("aria-label"), el.getAttribute("title")]
    : [el.getAttribute("aria-label"), labelOf(el), own, firstLine, el.getAttribute("title"), svgTitle])
    .map((n) => usable(clean(n))).filter(Boolean);
  const selectors = [];
  // Nur Kennungen, die nach Absicht aussehen – automatisch erzeugte (mit Ziffern) ändern sich beim nächsten Laden
  if (el.id && /^[A-Za-z][A-Za-z_-]*$/.test(el.id)) selectors.push("#" + el.id);
  const nm = el.getAttribute("name");
  if (nm && /^[A-Za-z][\\w-]*$/.test(nm)) selectors.push(`${tag}[name='${nm}']`);
  // Rückfall ohne Namen und Kennung: Art des Elements (das Passwortfeld, der Absende-Knopf …)
  if (tag === "input") selectors.push(type && type !== "text" ? `input[type='${type}']` : "input:not([type]), input[type='text']");
  else if (tag === "textarea" || tag === "button") selectors.push(tag === "button" && type === "submit" ? "button[type='submit']" : tag);
  else if (el.getAttribute("role")) selectors.push(`[role='${el.getAttribute("role")}']`);
  // Links ohne brauchbaren Text: das Ziel (ohne Abfrage-Teil, der wechselt oft) – dann die Art
  const href = tag === "a" ? (el.getAttribute("href") || "").split(/[?#]/)[0] : "";
  if (href && href.length <= 200 && !/['"\\\\\\s]/.test(href)) selectors.push(`a[href='${href}']`, `a[href^='${href}']`);
  if (tag === "a") selectors.push("a[href]");
  // Texte rundherum, vom engsten Umfeld nach außen (eigene Zeile, Karte, Abschnitt …) – zuerst der direkt davor
  const before = field ? usable(textBefore(el)) : "";
  const near = before ? [before] : [];
  let n = el.parentElement || el.getRootNode().host;
  for (let depth = 0; n && depth < 8 && near.length < 40; n = n.parentElement || n.getRootNode().host, depth++) {
    // Tabellenzellen trennt innerText mit Tabulator, Zeilen mit Umbruch – beides sind eigene Texte
    for (const line of (n.innerText || "").split(/[\\n\\t]/)) {
      const t = usable(clean(line));
      if (t && t.length >= 2 && !near.includes(t) && !names.includes(t)) near.push(t);
    }
  }
  const auto = (el.getAttribute("autocomplete") || "").toLowerCase();
  const hint = [labelOf(el), el.getAttribute("placeholder"), el.getAttribute("aria-label"), el.getAttribute("name"), el.id, before]
    .join(" ").toLowerCase();
  return { field, names: [...new Set(names)], selectors, near,
    label: names[0] || own.slice(0, nameMax) || before || selectors[0] || tag,
    secret: !field ? null : type === "password" || /password/.test(auto) || /passw|kennw|\\bpin\\b/.test(hint) ? "passwort"
      : type === "email" || auto === "email" || auto === "username" || /e-?mail|benutzer|user|login/.test(hint) ? "email" : null };
}"""
NAME_MAX = 60


async def _index_of(loc, n, mark):
    """An welcher Stelle der Treffer steht das markierte Element (oder None)?"""
    for i in range(min(n, _MAX_MATCHES)):
        if await loc.nth(i).get_attribute("data-last-scan") == mark:
            return i
    return None


async def _frame_of(page, mark):
    """In welchem Frame liegt das markierte Element (Marken sind über alle Frames eindeutig)?"""
    for frame in _frames(page):
        try:
            if await frame.locator(f'[data-last-scan="{mark}"]').count():
                return frame
        except Exception:                                   # noqa – Frame wurde gerade entfernt
            continue
    return None


async def find_target(page, mark):
    """Wie findet ein Schritt dieses Element sicher wieder? Lieber, wie ein Mensch es nennt: die Beschriftung;
    gibt es die mehrfach, mit einem Text in der Nähe („bei …“), zuletzt mit der Nummer („Nr. 2“).
    Jeder Vorschlag wird mit genau der Suche geprüft, die später beim Aufzeichnen läuft."""
    frame = await _frame_of(page, mark)
    about = await frame.evaluate(_ABOUT_JS, [mark, NAME_MAX]) if frame else None
    if not about:
        return None
    prefer = "fill" if about["field"] else "click"
    base = {"kind": "fill" if about["field"] else "click", "label": about["label"], "secret": about["secret"]}
    first_hit = None                                         # (Name, Treffer, Anzahl, Stelle) für die Rückfälle
    for name in about["names"] + about["selectors"]:
        try:
            loc, n = await _matches(page, name, prefer, wait_ms=0)
        except TimeoutError:
            continue
        i = await _index_of(loc, n, mark)
        if i is None:
            continue
        if n == 1:
            return {**base, "target": name}
        first_hit = first_hit or (name, loc, n, i)
    if not first_hit:
        return None
    name, loc, n, i = first_hit
    for near in about["near"]:
        if await _near(loc, n, near) == [i]:
            return {**base, "target": name, "near": near}
    return {**base, "target": name, "nth": i + 1}


async def snapshot(page):
    """Bildschirmfoto plus Lage aller Felder und Knöpfe darauf."""
    found = await page.evaluate(_COLLECT_JS, [SCAN_ELEMENTS, 0])
    elements, vw, vh = found["elements"], found["viewport"]["w"], found["viewport"]["h"]
    for k, frame in enumerate(_frames(page)[1:], start=1):
        if len(elements) >= SCAN_ELEMENTS or k > 9:
            break
        try:
            box = await (await frame.frame_element()).bounding_box()
            if not box or box["width"] < 2 or box["height"] < 2:
                continue
            inner = await frame.evaluate(_COLLECT_JS, [SCAN_ELEMENTS - len(elements), k * 1_000_000])
        except Exception:                                   # noqa – Frame lädt noch oder ist weg
            continue
        for e in inner["elements"]:
            b = e["box"]
            x, y = box["x"] + b["x"], box["y"] + b["y"]
            right = min(x + b["w"], box["x"] + box["width"], vw)
            bottom = min(y + b["h"], box["y"] + box["height"], vh)
            x, y = max(x, box["x"], 0), max(y, box["y"], 0)
            if right - x > 1 and bottom - y > 1:
                elements.append({**e, "box": {"x": x, "y": y, "w": right - x, "h": bottom - y}})
    shot = await page.screenshot(type="jpeg", quality=70)
    return {"url": page.url, "title": (await page.title())[:200], "viewport": found["viewport"],
            "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode("ascii"),
            "elements": elements}


async def element_thumb(page, mark):
    """Kleiner Ausschnitt rund um das Element – damit man es im Ablauf wiedererkennt."""
    frame = await _frame_of(page, mark)
    box = await frame.locator(f'[data-last-scan="{mark}"]').bounding_box() if frame else None
    if not box:
        return None
    pad = 6
    x, y = max(0, box["x"] - pad), max(0, box["y"] - pad)
    clip = {"x": x, "y": y, "width": max(1, min(box["width"] + 2 * pad, 480)),
            "height": max(1, min(box["height"] + 2 * pad, 120))}
    shot = await page.screenshot(type="jpeg", quality=75, clip=clip)
    return "data:image/jpeg;base64," + base64.b64encode(shot).decode("ascii")


async def page_text(page):
    try:
        return await page.locator("body").inner_text(timeout=2000)
    except Exception:                                       # noqa – Seite wechselt gerade
        return None


async def wait_if_writing(page, watch_s=1.0, wait_ms=120_000):
    """Läuft noch, was die Aktion angestoßen hat (eine KI denkt nach, eine Antwort wird gestreamt), oder schreibt
    die Seite noch? Dann warten, bis alles fertig ist. Liefert True, wenn es etwas zu warten gab."""
    before = await page_text(page)
    await page.wait_for_timeout(watch_s * 1000)
    if not activity(page).pending() and await page_text(page) == before:
        return False
    await _wait_settled(page, 2.0, wait_ms)
    return True
