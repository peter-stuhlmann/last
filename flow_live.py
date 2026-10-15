"""
Vorführen eines Ablaufs: ein unsichtbarer Browser bleibt offen, die Oberfläche zeigt sein Bildschirmfoto,
und jeder Klick darauf wird sofort ausgeführt – als genau der Schritt, der später aufgezeichnet wird.

Es gibt höchstens eine Sitzung gleichzeitig (die Oberfläche hat ja auch nur einen Nutzer). Sie schließt
sich nach LIVE_IDLE_S ohne Benutzung und spätestens nach LIVE_MAX_S. Gespeichert wird nichts; Zugangsdaten
kommen mit jeder Aktion neu und landen nie in einem Schritt (dort stehen nur Platzhalter).
"""

import asyncio
import time
import uuid

import llm_stresstest as lt
from flow_recorder import (
    VIEWPORT,
    _run_step,
    _short_error,
    describe,
    element_thumb,
    find_target,
    page_text,
    snapshot,
    wait_if_writing,
)
from flow_stresstest import STEP_TIMEOUT_MS, format_step

LIVE_IDLE_S = 600
LIVE_MAX_S = 3600
QUIET_STEP = {"kind": "wait_quiet", "quiet": 2.0}


class LiveSession:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.lock = asyncio.Lock()
        self.started = self.touched = time.monotonic()
        self._pw = self._browser = self.page = None

    @property
    def expired(self):
        now = time.monotonic()
        return now - self.touched > LIVE_IDLE_S or now - self.started > LIVE_MAX_S

    async def open(self, steps, secrets):
        """Browser starten und die bisherigen Schritte durchspielen. Scheitert einer, bleibt die Seite an dieser
        Stelle stehen – man sieht, wo es hakt, und kann von dort weitermachen."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise lt.PreflightError("Zum Vorführen wird ein Browser gebraucht (Playwright). Im Docker-Image ist er "
                                    "enthalten; sonst: python -m pip install playwright && playwright install chromium") from None
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await self._browser.new_context(viewport=VIEWPORT)
        self.page = await context.new_page()
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
        try:
            if t == "pick":
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
                await _run_step(page, step, secrets, {})
            if t != "fill" or action.get("enter"):
                # Schreibt die Seite noch (gestreamte Antwort) – oder hat sie im Messbereich neuen Inhalt bekommen,
                # ohne die Seite zu wechseln? Dann gehört Warten dazu, sonst fehlt beim Mitschneiden das Ende.
                writing = await wait_if_writing(page)
                changed = page.url == url and await page_text(page) != before
                if writing or (action.get("measuring") and changed):
                    steps.append(QUIET_STEP)
        except Exception as err:                            # noqa – erklären, Seite zeigen, weitermachen
            return {"error": f"Hat nicht geklappt: {_short_error(err)}.", "snapshot": await snapshot(page)}
        return {"steps": [format_step(s) for s in steps], "thumb": thumb, "snapshot": await snapshot(page)}

    async def close(self):
        for thing in (self._browser, self._pw):
            if thing is not None:
                try:
                    await (thing.close() if thing is self._browser else thing.stop())
                except Exception:                           # noqa – beim Aufräumen zählt nur, dass es weg ist
                    pass
        self._browser = self._pw = self.page = None


def _where(target):
    return {k: target[k] for k in ("target", "near", "nth") if target.get(k)}
