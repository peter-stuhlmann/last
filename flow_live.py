"""
Vorführen eines Ablaufs: ein unsichtbarer Browser bleibt offen, die Oberfläche zeigt sein Bildschirmfoto,
und jeder Klick darauf wird sofort ausgeführt – als genau der Schritt, der später aufgezeichnet wird.

Es gibt höchstens eine Sitzung gleichzeitig (die Oberfläche hat ja auch nur einen Nutzer). Sie schließt
sich nach LIVE_IDLE_S ohne Benutzung und spätestens nach LIVE_MAX_S. Gespeichert wird nichts; Zugangsdaten
kommen mit jeder Aktion neu und landen nie in einem Schritt (dort stehen nur Platzhalter).
"""

import asyncio
import base64
import json
import time
import uuid

import llm_stresstest as lt
from flow_recorder import (
    VIEWPORT,
    _frame_of,
    _jpeg,
    _run_step,
    _settle,
    _short_error,
    activity,
    describe,
    element_thumb,
    find_target,
    mark_at,
    page_text,
    snapshot,
    wait_if_writing,
)
from flow_stresstest import STEP_TIMEOUT_MS, browser_credentials, format_step

LIVE_IDLE_S = 600
LIVE_MAX_S = 3600
LOOK_TIMEOUT_S = 5
QUIET_STEP = {"kind": "wait_quiet", "quiet": 2.0}
# Tasten, die als Schritt „drücke …“ aufgenommen werden, wenn gerade nichts getippt wird
RECORDED_KEYS = {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Space"}

# Welches Element hat gerade den Fokus – und ist es ein Eingabefeld? (bekommt eine Marke wie beim Abtasten)
_FOCUS_JS = """([base]) => {
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!el || el === document.body) return null;
  const type = (el.getAttribute("type") || "").toLowerCase();
  const field = el.tagName === "TEXTAREA" || el.isContentEditable || el.getAttribute("role") === "textbox" ||
    (el.tagName === "INPUT" && ["", "text", "email", "password", "search", "tel", "url", "number"].includes(type));
  if (!field) return null;
  if (window.__lastScanNext === undefined) window.__lastScanNext = base + Math.floor(Math.random() * 900000);
  let mark = el.getAttribute("data-last-scan");
  if (!mark) { mark = String(window.__lastScanNext++); el.setAttribute("data-last-scan", mark); }
  return mark;
}"""
_VALUE_JS = """(mark) => {
  const el = document.querySelector(`[data-last-scan="${mark}"]`);
  return el ? (el.value !== undefined ? el.value : (el.innerText || "")) : null;
}"""


class LiveSession:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.lock = asyncio.Lock()
        self.started = self.touched = time.monotonic()
        self._pw = self._browser = self.page = None
        self._looking = False
        # Live-Strom: neuestes Bild, Meldungen an die Oberfläche, Eingaben in Reihenfolge
        self._cdp = None
        self._frame, self._seq, self._sent = None, 0, 0
        self._wake = asyncio.Event()
        self._out = []
        self._inbox = asyncio.Queue()
        self._worker = None
        self._acting = False
        self._typing = None                                 # Marke des Feldes, in das gerade getippt wird

    @property
    def expired(self):
        now = time.monotonic()
        return now - self.touched > LIVE_IDLE_S or now - self.started > LIVE_MAX_S

    async def open(self, steps, secrets, site_auth=None):
        """Browser starten und die bisherigen Schritte durchspielen. Scheitert einer, bleibt die Seite an dieser
        Stelle stehen – man sieht, wo es hakt, und kann von dort weitermachen."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise lt.PreflightError("Zum Vorführen wird ein Browser gebraucht (Playwright). Im Docker-Image ist er "
                                    "enthalten; sonst: python -m pip install playwright && playwright install chromium") from None
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await self._browser.new_context(viewport=VIEWPORT,
                                                   http_credentials=browser_credentials(site_auth, steps[0]["url"]))
        self.page = await context.new_page()
        activity(self.page)
        self.page.set_default_timeout(STEP_TIMEOUT_MS)
        state = {"measuring": False}
        done, error = 0, None
        for step in steps:
            try:
                await _run_step(self.page, step, secrets, state)
            except Exception as err:                        # noqa – erklären statt abbrechen
                if step["kind"] == "open":
                    raise lt.PreflightError(f"Die Startseite lässt sich nicht öffnen: {_short_error(err)}.") from None
                error = {"index": done, "message": f"„{describe(step)}“ hat nicht geklappt: {_short_error(err)}."}
                break
            done += 1
        return {"session": self.id, "steps_done": done, "error": error, "snapshot": await snapshot(self.page)}

    async def act(self, action, secrets):
        """Eine Aktion auf der Seite. Liefert die entstandenen Schritte (als Zeilen der Schritt-Sprache)
        und das neue Bildschirmfoto – oder bei einem Feld erst die Rückfrage, was hinein soll.
        measuring: die Aktion gehört schon zum Messbereich."""
        self.touched = time.monotonic()
        page, t = self.page, action["type"]
        steps, thumb = [], None
        if t == "scroll":
            # Blättern ist kein Schritt – beim Abspielen findet der Browser die Elemente auch weiter unten.
            # Mit der Maus an der Stelle, damit auch innere Bereiche (Seitenleiste, Hauptteil) blättern.
            try:
                await page.mouse.move(action["x"], action["y"])
                await page.mouse.wheel(0, action["dy"])
                await page.wait_for_timeout(350)
            except Exception as err:                        # noqa – erklären, Seite zeigen
                return {"error": f"Blättern hat nicht geklappt: {_short_error(err)}.", "snapshot": await snapshot(page)}
            return {"steps": [], "snapshot": await snapshot(page)}
        try:
            if t == "pick_at":
                mark = await mark_at(page, action["x"], action["y"])
                if mark is None:
                    return {"error": "Dort ist nichts Anklickbares. Probier eine andere Stelle oder die Tab-Taste.",
                            "snapshot": await snapshot(page)}
                action = {**action, "type": "pick", "mark": mark}
                t = "pick"
            if t == "pick":
                if await _frame_of(page, action["mark"]) is None:
                    return {"error": "Die Seite hat sich gerade geändert – bitte noch einmal klicken.",
                            "snapshot": await snapshot(page)}
                target = await find_target(page, action["mark"])
                if target is None:
                    return {"error": "Dieses Element lässt sich nicht sicher wiederfinden – bitte ein anderes "
                                     "wählen oder es per Tastatur erreichen (Tab).", "snapshot": await snapshot(page)}
                thumb = await element_thumb(page, action["mark"])
                if target["kind"] == "fill":
                    return {"need": "text", "target": target, "thumb": thumb}
                steps.append({"kind": "click", **_where(target)})
            elif t == "fill":
                steps.append({"kind": "fill", **_where(action["target"]), "text": action["text"]})
                if action.get("enter"):
                    steps.append({"kind": "press", "key": "Enter"})
            elif t == "press":
                steps.append({"kind": "press", "key": action["key"]})
            url, before = page.url, await page_text(page)
            for step in steps:
                await _run_step(page, step, secrets, {"quick": True})
            if t != "fill" or action.get("enter"):
                # Schreibt die Seite noch (gestreamte Antwort) – oder hat sie im Messbereich neuen Inhalt bekommen,
                # ohne die Seite zu wechseln? Dann gehört Warten dazu, sonst fehlt beim Mitschneiden das Ende.
                # Ein Klick löst selten eine lange Antwort aus; Enter (Chat abschicken) oft – dort genauer hinsehen
                writing = await wait_if_writing(page, 1.0 if t in ("fill", "press") else 0.5)
                changed = page.url == url and await page_text(page) != before
                if writing or (action.get("measuring") and changed):
                    steps.append(QUIET_STEP)
        except Exception as err:                            # noqa – erklären, Seite zeigen, weitermachen
            return {"error": f"Hat nicht geklappt: {_short_error(err)}.", "snapshot": await snapshot(page)}
        return {"steps": [format_step(s) for s in steps], "thumb": thumb, "snapshot": await snapshot(page)}

    async def look(self):
        """Nur hinsehen: ein frisches Bild, auch während eine Aktion noch wartet (die Oberfläche fragt laufend)."""
        self.touched = time.monotonic()
        if self._looking:                                   # das letzte Bild ist noch in Arbeit (träge Seite)
            return {"snapshot": None}
        self._looking = True
        try:
            return {"snapshot": await asyncio.wait_for(snapshot(self.page), LOOK_TIMEOUT_S)}
        except Exception:                                   # noqa – Seite wechselt gerade; beim nächsten Mal
            return {"snapshot": None}
        finally:
            self._looking = False

    # ── Live-Strom: die Seite als Video, Eingaben direkt an den Browser ──────────────────────────────────

    async def start_stream(self):
        """Bild für Bild an die Oberfläche (CDP-Screencast) – Chromium schickt nur, wenn sich etwas ändert."""
        self._cdp = await self.page.context.new_cdp_session(self.page)
        self._cdp.on("Page.screencastFrame", self._on_frame)
        await self._cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 70, "maxWidth": VIEWPORT["width"],
                                                       "maxHeight": VIEWPORT["height"], "everyNthFrame": 1})
        self.page.on("framenavigated", lambda f: f == self.page.main_frame and self._state())
        self._worker = asyncio.ensure_future(self._work())
        self._state()
        # Das erste Bild gleich, auch wenn die Seite still steht
        self._frame = base64.b64encode(await _jpeg(self.page, 70)).decode("ascii")
        self._seq += 1
        self._wake.set()

    def _on_frame(self, params):
        self._frame, self._seq = params["data"], self._seq + 1
        self._wake.set()
        asyncio.ensure_future(self._ack(params["sessionId"]))

    async def _ack(self, session_id):
        try:
            await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception:                                   # noqa – Sitzung wurde geschlossen
            pass

    def _say(self, **msg):
        self._out.append(msg)
        self._wake.set()

    def _state(self):
        try:
            self._say(t="state", url=self.page.url)
        except Exception:                                   # noqa – Seite ist weg
            pass

    async def events(self):
        """Die nächsten Meldungen für die Oberfläche als (Art, Text) – wartet, bis es etwas gibt."""
        try:
            await asyncio.wait_for(self._wake.wait(), 15)
        except TimeoutError:
            return [("ping", "")]
        self._wake.clear()
        self.touched = time.monotonic()
        out = [("msg", json.dumps(m)) for m in self._out]
        self._out.clear()
        if self._seq != self._sent and self._frame:
            self._sent = self._seq
            out.append(("frame", self._frame))
        return out

    def put(self, events, measuring=False):
        """Eingaben der Oberfläche. Maus und Rad gehen sofort durch; was einen Schritt ergibt (Klick, Taste, Text),
        wartet in der Reihe – in genau der Reihenfolge, in der der Nutzer es getan hat."""
        self.touched = time.monotonic()
        for ev in events:
            if ev["t"] in ("move", "wheel"):
                asyncio.ensure_future(self._pointer(ev))
            else:
                self._inbox.put_nowait((ev, measuring))

    async def _pointer(self, ev):
        if self._acting or self.page is None:               # mitten in einem Klick würde Verschieben ihn zum Ziehen machen
            return
        try:
            await self.page.mouse.move(ev["x"], ev["y"])
            if ev["t"] == "wheel":
                await self.page.mouse.wheel(ev.get("dx", 0), ev.get("dy", 0))
        except Exception:                                   # noqa – Seite wechselt gerade
            pass

    async def _work(self):
        while True:
            ev, measuring = await self._inbox.get()
            self._acting = True
            self._say(t="busy", on=True)
            try:
                async with self.lock:
                    await self._handle(ev, measuring)
            except Exception as err:                        # noqa – erklären, weitermachen
                self._say(t="notice", text=f"Hat nicht geklappt: {_short_error(err)}.")
            finally:
                self._acting = False
                self._say(t="busy", on=False)

    async def _handle(self, ev, measuring):
        page = self.page
        if ev["t"] == "click":
            await self._commit(False)
            url, before = page.url, await page_text(page)
            mark = await mark_at(page, ev["x"], ev["y"])
            target = await find_target(page, mark) if mark else None
            if target is None:
                self._say(t="notice", text="Dieses Element lässt sich nicht sicher wiederfinden – es ist nichts passiert. "
                                           "Bitte ein anderes wählen oder mit der Tab-Taste hinkommen.")
                return
            thumb = await element_thumb(page, mark) if target["kind"] == "click" else None
            await page.mouse.click(ev["x"], ev["y"], click_count=2 if ev.get("dbl") else 1)
            await _settle(page, True)
            if target["kind"] == "fill":                    # nur der Fokus – der Schritt entsteht beim Tippen
                return
            steps = [{"kind": "click", **_where(target)}]
            steps += await self._after(page, url, before, measuring, long_wait=False)
            self._say(t="steps", steps=[format_step(s) for s in steps], thumb=thumb)
        else:
            await self._keys(ev, measuring)

    async def _keys(self, ev, measuring):
        page, t = self.page, ev["t"]
        key, mods = ev.get("key", ""), ev.get("mods") or []
        if t in ("type", "text") or key in ("Backspace", "Delete"):
            await self._ensure_typing()
        if t == "type" and ev["text"] == " " and not self._typing:
            ev, t, key = {"t": "key", "key": " "}, "key", " "     # Leertaste auf einem Knopf: ein Schritt, kein Text
        if t == "type":
            await page.keyboard.type(ev["text"])
        elif t == "text":
            await page.keyboard.insert_text(ev["text"])
        elif key in ("Enter", "Tab") and not mods and self._typing:
            url, before = page.url, await page_text(page)
            await self._commit(key == "Enter")
            await page.keyboard.press(key)
            await _settle(page, True)
            if key == "Enter":
                steps = await self._after(page, url, before, measuring, long_wait=True)
                if steps:
                    self._say(t="steps", steps=[format_step(s) for s in steps], thumb=None)
        else:
            name = "Space" if key == " " else key
            if self._typing and not mods and name not in ("Backspace", "Delete", "Home", "End") and not name.startswith("Arrow"):
                await self._commit(False)                   # Escape o. Ä.: das Feld ist fertig
            record = not mods and name in RECORDED_KEYS and not self._typing
            url, before = page.url, await page_text(page)
            await page.keyboard.press("+".join([*mods, name]))
            if record:
                await _settle(page, True)
                steps = [{"kind": "press", "key": name}]
                steps += await self._after(page, url, before, measuring, long_wait=name == "Enter")
                self._say(t="steps", steps=[format_step(s) for s in steps], thumb=None)

    async def _ensure_typing(self):
        mark = await self.page.evaluate(_FOCUS_JS, [0])
        if mark is None or mark == self._typing:
            return
        await self._commit(False)
        self._typing = mark

    async def _commit(self, enter):
        """Das Getippte als Schritt aufnehmen: Der Wert steht im Feld, so wie die Seite ihn sieht."""
        mark, self._typing = self._typing, None
        if mark is None:
            return
        page = self.page
        value = await page.evaluate(_VALUE_JS, mark)
        target = await find_target(page, mark) if value is not None else None
        if target is None or target["kind"] != "fill":
            self._say(t="notice", text="Dieses Feld lässt sich nicht sicher wiederfinden – das Getippte ist nicht im "
                                       "Ablauf. Bitte ein anderes Feld oder die Tab-Taste.")
            return
        self._say(t="fill", target=target, value=value, enter=enter, thumb=await element_thumb(page, mark))

    async def _after(self, page, url, before, measuring, long_wait):
        """Schreibt die Seite noch (gestreamte Antwort) oder hat sie im Messbereich neuen Inhalt? Dann gehört Warten
        dazu, sonst fehlt beim Mitschneiden das Ende."""
        writing = await wait_if_writing(page, 1.0 if long_wait else 0.5)
        changed = page.url == url and await page_text(page) != before
        return [QUIET_STEP] if writing or (measuring and changed) else []

    async def close(self):
        if self._worker is not None:
            self._worker.cancel()
        for thing in (self._browser, self._pw):
            if thing is not None:
                try:
                    await (thing.close() if thing is self._browser else thing.stop())
                except Exception:                           # noqa – beim Aufräumen zählt nur, dass es weg ist
                    pass
        self._browser = self._pw = self.page = None


def _where(target):
    return {k: target[k] for k in ("target", "near", "nth") if target.get(k)}
