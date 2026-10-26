"""Aufzeichnen mit echtem Browser und anschließendes Abspielen – braucht Chromium (im Docker-Image enthalten)."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
import uuid

from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flow_stresstest as fl  # noqa: E402
import stresstest_web as sw  # noqa: E402

try:
    import playwright  # noqa: F401
    HAS_BROWSER = True
except ImportError:
    HAS_BROWSER = False

LOGIN_PAGE = """<!doctype html><html lang="de"><body>
<h1>Anmelden</h1>
<form id="f"><label>E-Mail <input name="email" type="email"></label>
<label>Passwort <input name="pw" type="password"></label>
<button type="submit">Anmelden</button></form>
<script>
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch('/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email: f.email.value, pw: f.pw.value})});
  if (r.ok) location.href = '/chat'; else document.body.insertAdjacentHTML('beforeend', '<p>Falsch</p>');
};
</script></body></html>"""

CHAT_PAGE = """<!doctype html><html lang="de"><body>
<h1>Willkommen, Tester</h1>
<label>Nachricht <input id="msg"></label> <button id="send">Senden</button>
<div class="antwort"></div>
<script>
async function send() {
  const out = document.querySelector('.antwort'); out.textContent = '';
  const c = await (await fetch('/api/conversations', {method: 'POST', headers: {'Content-Type': 'application/json',
    'X-Requested-With': 'chat'}, body: '{}'})).json();
  const r = await fetch('/api/conversations/' + c.data.id + '/messages', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: document.getElementById('msg').value})});
  const reader = r.body.getReader(); const dec = new TextDecoder();
  for (;;) { const {done, value} = await reader.read(); if (done) break;
    for (const line of dec.decode(value).split('\\n')) if (line.startsWith('data: ') && !line.includes('[DONE]'))
      out.textContent += line.slice(6) + ' '; }
}
document.getElementById('send').onclick = send;
document.getElementById('msg').addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
</script></body></html>"""

STEPS = """
öffne {base}/login
tippe in "E-Mail" {email}
tippe in "Passwort" {passwort}
klicke "Anmelden"
warte auf Text "Willkommen"
messen ab hier
tippe in "Nachricht" "Was ist ein Lasttest?"
drücke Enter
warte auf erste Antwort in ".antwort"
warte bis ".antwort" fertig ist (1 s ruhig)
"""


class ChatSite:
    USERS = {("tester@example.de", "sehr-geheim-42"): "sitzung-abcdefgh",
             ("zweite@example.de", "auch-geheim-43"): "sitzung-zweitesk"}

    def __init__(self):
        self.known = set()
        self.messages = []
        self.sessions_seen = []
        self.think = 0.1                     # so lange „denkt“ die KI, bevor das erste Wort kommt

    async def handle(self, req):
        p = req.path
        if p == "/login" and req.method == "GET":
            return web.Response(text=LOGIN_PAGE, content_type="text/html")
        if p == "/login" and req.method == "POST":
            data = await req.json()
            sid = self.USERS.get((data.get("email"), data.get("pw")))
            if not sid:
                return web.json_response({"error": "falsch"}, status=401)
            resp = web.json_response({"ok": True})
            resp.set_cookie("sid", sid, httponly=True)
            return resp
        if req.cookies.get("sid") not in self.USERS.values():
            return web.json_response({"error": "kein Zugriff"}, status=401)
        self.sessions_seen.append(req.cookies.get("sid"))
        if p == "/chat":
            return web.Response(text=CHAT_PAGE, content_type="text/html")
        if p == "/api/conversations":
            cid = str(uuid.uuid4())
            self.known.add(cid)
            return web.json_response({"data": {"id": cid}}, status=201)
        if p.startswith("/api/conversations/") and p.endswith("/messages"):
            cid = p.split("/")[3]
            if cid not in self.known:
                return web.json_response({"error": "unbekannt"}, status=404)
            self.messages.append((cid, (await req.json())["text"]))
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(req)
            await asyncio.sleep(self.think)
            for word in ("Ein", "Lasttest", "prüft", "die", "Belastbarkeit."):
                await resp.write(f"data: {word}\n\n".encode())
                await asyncio.sleep(0.02)
            await resp.write(b"data: [DONE]\n\n")
            return resp
        return web.Response(status=404)

    async def start(self):
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        return f"http://127.0.0.1:{self.runner.addresses[0][1]}"


@unittest.skipUnless(HAS_BROWSER, "Playwright/Chromium nicht installiert")
class Aufzeichnen(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.site = ChatSite()
        self.base = await self.site.start()
        self.out = tempfile.mkdtemp()

    async def asyncTearDown(self):
        await self.site.runner.cleanup()

    def args(self, **over):
        cfg = {"kind": "flow", "confirm_owner": True, "steps": STEPS.replace("{base}", self.base),
               "secrets": {"email": "tester@example.de", "passwort": "sehr-geheim-42"},
               "levels": "1,2", "level_seconds": 1, "warmup_seconds": 0, "min_samples": 2, "baseline_requests": 2,
               "cooldown": 0, "spike_idle": 0, "tests": "baseline,ramp", **over}
        return sw.build_args(cfg)

    async def test_aufzeichnen_und_abspielen(self):
        st = fl.FlowStressTest(self.args(), self.out)
        await st.run()
        s = st.summary
        pre = s["prechecks"]
        self.assertEqual(len(pre["steps"]), 10)
        self.assertTrue(all(os.path.isfile(os.path.join(self.out, sh["screenshot"])) for sh in pre["steps"]))
        self.assertEqual([q["method"] for q in pre["requests"]], ["POST", "POST"])
        self.assertTrue(pre["requests"][1]["stream"])
        self.assertEqual(pre["requests"][1]["dynamic"], ["v1"])
        self.assertEqual(pre["main"], 1)
        self.assertIn("x-requested-with", pre["requests"][0]["header_names"])
        # Abspielen: jede Wiederholung mit eigener Chat-ID und der getippten Nachricht
        self.assertEqual(s["baseline"]["errors"], 0)
        self.assertGreaterEqual(len(self.site.messages), 2 + 2)
        self.assertEqual(len({cid for cid, _ in self.site.messages}), len(self.site.messages))
        self.assertTrue(all(text == "Was ist ein Lasttest?" for _, text in self.site.messages))
        self.assertGreater(s["baseline"]["ttft_p50"], 0.08)
        self.assertEqual(s["verdict"]["status"] in ("good", "warn", "bad"), True)
        # Nirgends Zugangsdaten oder Sitzungs-Cookie
        for name in os.listdir(self.out):
            if name.endswith(".png"):
                continue
            with open(os.path.join(self.out, name), encoding="utf-8", errors="replace") as f:
                content = f.read()
            for secret in ("sehr-geheim-42", "sitzung-abcdefgh", "tester@example.de"):
                self.assertNotIn(secret, content, name)

    async def test_mehrere_konten_werden_aufgezeichnet_und_reihum_benutzt(self):
        st = fl.FlowStressTest(self.args(accounts=[{"email": "tester@example.de", "passwort": "sehr-geheim-42"},
                                                   {"email": "zweite@example.de", "passwort": "auch-geheim-43"}],
                                         secrets=None), self.out)
        await st.run()
        pre = st.summary["prechecks"]
        self.assertEqual(pre["accounts"], 2)
        self.assertEqual(len(pre["steps"]), 10)                 # Fotos nur vom ersten Konto
        self.assertEqual(st.summary["baseline"]["errors"], 0)
        used = {s for s in self.site.sessions_seen if s}
        self.assertEqual(used, {"sitzung-abcdefgh", "sitzung-zweitesk"})
        for name in os.listdir(self.out):
            if name.endswith(".png"):
                continue
            with open(os.path.join(self.out, name), encoding="utf-8", errors="replace") as f:
                content = f.read()
            for secret in ("auch-geheim-43", "sitzung-zweitesk", "zweite@example.de"):
                self.assertNotIn(secret, content, name)

    async def test_fehler_im_schritt_wird_erklaert(self):
        st = fl.FlowStressTest(self.args(secrets={"email": "tester@example.de", "passwort": "falsch"}), self.out)
        with self.assertRaises(sw.lt.PreflightError) as ctx:
            await st.run()
        msg = str(ctx.exception)
        self.assertIn("Zeile 6", msg)                      # „warte auf Text Willkommen“ scheitert
        self.assertIn("Willkommen", msg)
        self.assertNotIn("falsch", msg)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "schritt_fehler.png")))


LIST_PAGE = """<!doctype html><html lang="de"><body>
<h1>Bestellungen</h1>
<table>
<tr><td>Bestellung 4711</td><td><button onclick="done('4711')">Löschen</button></td></tr>
<tr><td>Bestellung 4712</td><td><button onclick="done('4712')">Löschen</button></td></tr>
</table>
<div><button onclick="done('a')">Löschen</button></div><div><button onclick="done('b')">Löschen</button></div>
<p id="out"></p>
<script>function done(x) { document.getElementById('out').textContent = 'weg: ' + x; }</script>
</body></html>"""


# Eine Single-Page-App: Das HTML ist leer, das Skript kommt verzögert und holt erst noch Daten
SPA_PAGE = """<!doctype html><html lang="de"><body><div id="app"></div><script async src="/app.js"></script></body></html>"""
SPA_JS = """fetch('/daten').then(r => r.json()).then(d => {
  document.getElementById('app').innerHTML = '<h1>' + d.titel + '</h1><button>Weiter</button>';
});"""


# Anmeldungen, die nicht nach Lehrbuch gebaut sind – jede schickt E-Mail und Passwort an /anmelden
LOGIN_FORMS = {
    # keine Beschriftung, nur Text davor; automatische IDs; Knopf nur mit Symbol
    "/ohne-beschriftung": """<form method="post" action="/anmelden"><div>Benutzer</div><input id="in-8f3a1" name="email">
      <div>Kennwort</div><input id="in-2b7c9" name="passwort" type="password">
      <button type="submit"><svg width="20" height="20"><circle cx="10" cy="10" r="8"/></svg></button></form>""",
    # Web Component (Shadow DOM)
    "/shadow": """<login-box></login-box><script>customElements.define('login-box', class extends HTMLElement {
      connectedCallback() { this.attachShadow({mode: 'open'}).innerHTML = '<form method="post" action="/anmelden">' +
        '<label>E-Mail <input name="email"></label><label>Passwort <input name="passwort" type="password"></label>' +
        '<button>Anmelden</button></form>'; } });</script>""",
    # eingebettetes Anmeldefenster (iframe)
    "/eingebettet": """<h1>Portal</h1><iframe src="/rahmen" width="500" height="300"></iframe>""",
    # Kacheln wie in einem Dashboard: ganzer Link mit langem Text, daneben ein Pfeil-Link nur mit Symbol;
    # der Hauptteil blättert für sich (innerer Bereich), ganz unten noch ein Knopf
    "/kacheln": """<div style="display:flex;height:100vh"><nav style="width:200px"><a href="/modul/a">Dashboard</a></nav>
      <main id="haupt" style="flex:1;overflow-y:auto">""" + "".join(
        f"""<div class="kachel" style="display:flex;margin:20px;border:1px solid #ccc">
          <a href="/modul/{k}?von=start" style="flex:1;padding:20px;display:block"><b>{name}</b><br>{text}</a>
          <a href="/modul/{k}/los" style="width:60px;background:#00a;display:block"><svg width="20" height="20"><path d="M2 10h16"/></svg></a>
        </div>""" for k, name, text in (
            ("a", "KnowledgeBot (Intern)", "Intelligente Unterstützung für Analysen und Auswertungen im ganzen Unternehmen"),
            ("b", "Web-Recherche (Extern)", "KI-gestützte Recherche aus dem gesamten öffentlichen Internet mit Quellen"))) + """
      <div style="height:1600px"></div><button onclick="document.body.append('Unten geklickt')">Ganz unten</button></main></div>""",
    "/rahmen": """<form method="post" action="/anmelden" target="_top"><label for="e">E-Mail</label><input id="e" name="email">
      <label for="p">Passwort</label><input id="p" name="passwort" type="password"><button>Anmelden</button></form>""",
}


class ListSite(ChatSite):
    async def handle(self, req):
        if req.path == "/liste":
            return web.Response(text=LIST_PAGE, content_type="text/html")
        if req.path in LOGIN_FORMS:
            return web.Response(text=f"<!doctype html><html lang='de'><body>{LOGIN_FORMS[req.path]}</body></html>",
                                content_type="text/html")
        if req.path.startswith("/modul/"):
            self.visited.append(req.path)
            return web.Response(text=f"<h1>Modul {req.path}</h1>", content_type="text/html")
        if req.path == "/anmelden" and req.method == "POST":
            self.logins.append(dict(await req.post()))
            return web.Response(text="<h1>Willkommen</h1>", content_type="text/html")
        if req.path == "/spa":
            return web.Response(text=SPA_PAGE, content_type="text/html")
        if req.path == "/app.js":
            await asyncio.sleep(0.5)
            return web.Response(text=SPA_JS, content_type="application/javascript")
        if req.path == "/daten":
            await asyncio.sleep(0.3)
            return web.json_response({"titel": "Willkommen"})
        return await super().handle(req)


@unittest.skipUnless(HAS_BROWSER, "Playwright/Chromium nicht installiert")
class Vorfuehren(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import flow_live
        self.site = ListSite()
        self.base = await self.site.start()
        self.live = flow_live.LiveSession()

    async def asyncTearDown(self):
        await self.live.close()
        await self.site.runner.cleanup()

    async def open(self, path="/login", lines="", **secrets):
        return await self.live.open(fl.parse_steps(f"öffne {self.base}{path}\n{lines}", partial=True), secrets)

    @staticmethod
    def mark(snap, label):
        return next(e["mark"] for e in snap["elements"] if e["label"] == label)

    async def stream(self, *events, wait=1.5):
        """Eingaben wie von der Oberfläche schicken und sammeln, was der Strom meldet (Bilder und Meldungen)."""
        got = []

        async def pump():
            while True:
                for kind, data in await self.live.events():
                    got.append((kind, json.loads(data) if kind == "msg" else data))

        task = asyncio.ensure_future(pump())
        try:
            self.live.put(list(events))
            await asyncio.sleep(wait)
        finally:
            task.cancel()
        return got

    async def test_live_strom_bilder_und_schritte_aus_echten_eingaben(self):
        r = await self.open()
        await self.live.start_stream()
        box = {e["label"]: e["box"] for e in r["snapshot"]["elements"]}
        mid = lambda b: (b["x"] + b["w"] / 2, b["y"] + b["h"] / 2)  # noqa: E731
        (ex, ey), _, (bx, by) = mid(box["E-Mail"]), mid(box["Passwort"]), mid(box["Anmelden"])
        got = await self.stream({"t": "click", "x": ex, "y": ey}, {"t": "type", "text": "tester@example.de"},
                                {"t": "key", "key": "Tab"}, {"t": "type", "text": "sehr-geheim-42"},
                                {"t": "click", "x": bx, "y": by}, wait=4)
        self.assertTrue(any(k == "frame" and len(d) > 100 for k, d in got), "es kommen Bilder")
        msgs = [d for k, d in got if k == "msg"]
        fills = [m for m in msgs if m["t"] == "fill"]
        self.assertEqual([(m["target"]["target"], m["value"], m["target"]["secret"]) for m in fills],
                         [("E-Mail", "tester@example.de", "email"), ("Passwort", "sehr-geheim-42", "passwort")])
        self.assertIn(["klicke \"Anmelden\""], [m["steps"] for m in msgs if m["t"] == "steps"])
        self.assertTrue(self.live.page.url.endswith("/chat"))

    async def test_live_strom_klick_auf_nicht_wiederfindbares_tut_nichts(self):
        await self.open("/spa")
        await self.live.start_stream()
        got = await self.stream({"t": "click", "x": 3, "y": 790})          # leere Fläche
        msgs = [d for k, d in got if k == "msg"]
        self.assertTrue(any(m["t"] == "notice" for m in msgs))
        self.assertFalse(any(m["t"] in ("steps", "fill") for m in msgs))

    async def test_single_page_app_ist_beim_ersten_bild_schon_aufgebaut(self):
        r = await self.open("/spa")
        self.assertIsNone(r["error"])
        self.assertEqual([e["label"] for e in r["snapshot"]["elements"]], ["Weiter"])

    async def test_anmelden_und_chatten_durch_klicken(self):
        r = await self.open()
        self.assertIsNone(r["error"])
        snap = r["snapshot"]
        self.assertTrue(snap["screenshot"].startswith("data:image/jpeg;base64,"))
        self.assertTrue(all(e["box"]["w"] > 0 for e in snap["elements"]))
        secrets = {"email": "tester@example.de", "passwort": "sehr-geheim-42"}

        # Ein Feld: erst die Rückfrage, was hinein soll – samt Vorschlag für den Platzhalter
        ask = await self.live.act({"type": "pick", "mark": self.mark(snap, "E-Mail")}, secrets)
        self.assertEqual(ask["need"], "text")
        self.assertEqual((ask["target"]["target"], ask["target"]["secret"]), ("E-Mail", "email"))
        self.assertTrue(ask["thumb"].startswith("data:image/jpeg"))
        r = await self.live.act({"type": "fill", "target": ask["target"], "text": "{email}"}, secrets)
        self.assertEqual(r["steps"], ['tippe in "E-Mail" {email}'])
        ask = await self.live.act({"type": "pick", "mark": self.mark(r["snapshot"], "Passwort")}, secrets)
        r = await self.live.act({"type": "fill", "target": ask["target"], "text": "{passwort}"}, secrets)
        self.assertEqual(r["steps"], ['tippe in "Passwort" {passwort}'])

        # Ein Knopf: wird sofort geklickt, die nächste Seite ist danach geladen
        r = await self.live.act({"type": "pick", "mark": self.mark(r["snapshot"], "Anmelden")}, secrets)
        self.assertEqual(r.get("steps"), ['klicke "Anmelden"'], r.get("error"))
        self.assertTrue(r["snapshot"]["url"].endswith("/chat"))

        # Text mit Enter: die gestreamte Antwort wird erkannt und Warten ergänzt
        ask = await self.live.act({"type": "pick", "mark": self.mark(r["snapshot"], "Nachricht")}, secrets)
        r = await self.live.act({"type": "fill", "target": ask["target"], "text": "Was ist ein Lasttest?", "enter": True,
                                 "measuring": True}, secrets)
        self.assertEqual(r["steps"], ['tippe in "Nachricht" "Was ist ein Lasttest?"', "drücke Enter",
                                      "warte bis die Seite ruhig ist (2 s)"])
        self.assertEqual(len(self.site.messages), 1)
        self.assertNotIn("sehr-geheim-42", json.dumps(r))

        # Was so entstanden ist, lässt sich genau so aufzeichnen
        lines = ['tippe in "E-Mail" {email}', 'tippe in "Passwort" {passwort}', 'klicke "Anmelden"', "messen ab hier",
                 'tippe in "Nachricht" "Was ist ein Lasttest?"', "drücke Enter", "warte bis die Seite ruhig ist (2 s)"]
        args = sw.build_args({"kind": "flow", "confirm_owner": True, "secrets": secrets,
                              "steps": f"öffne {self.base}/login\n" + "\n".join(lines)})
        from flow_recorder import record
        plans, info = await record(args, tempfile.mkdtemp())
        self.assertEqual([q["method"] for q in info["requests"]], ["POST", "POST"])

    async def test_ki_denkt_lange_nach_es_wird_auf_die_ganze_antwort_gewartet(self):
        self.site.think = 4.0
        secrets = {"email": "tester@example.de", "passwort": "sehr-geheim-42"}
        r = await self.open(lines='tippe in "E-Mail" {email}\ntippe in "Passwort" {passwort}\nklicke "Anmelden"', **secrets)
        ask = await self.live.act({"type": "pick", "mark": self.mark(r["snapshot"], "Nachricht")}, secrets)
        r = await self.live.act({"type": "fill", "target": ask["target"], "text": "Was ist ein Lasttest?", "enter": True,
                                 "measuring": True}, secrets)
        self.assertEqual(r["steps"][-1], "warte bis die Seite ruhig ist (2 s)")
        self.assertIn("Belastbarkeit", await self.live.page.inner_text(".antwort"))
        self.assertTrue((await self.live.look())["snapshot"]["screenshot"].startswith("data:image/jpeg"))

        # Aufzeichnen mit diesem Ablauf: die gestreamte Antwort ist drin, nicht nur die Frage
        lines = ['tippe in "E-Mail" {email}', 'tippe in "Passwort" {passwort}', 'klicke "Anmelden"', "messen ab hier",
                 *r["steps"]]
        args = sw.build_args({"kind": "flow", "confirm_owner": True, "secrets": secrets,
                              "steps": f"öffne {self.base}/login\n" + "\n".join(lines)})
        from flow_recorder import record
        plans, info = await record(args, tempfile.mkdtemp())
        self.assertEqual([q["method"] for q in info["requests"]], ["POST", "POST"])
        self.assertTrue(info["requests"][info["main"]]["stream"])

    async def test_alte_marke_nach_seitenwechsel(self):
        r = await self.open()
        old = self.mark(r["snapshot"], "Anmelden")
        await self.live.page.goto(f"{self.base}/liste")
        r = await self.live.act({"type": "pick", "mark": old}, {})
        self.assertIn("geändert", r["error"])

    async def login_by_clicking(self, path):
        """Wie ein Mensch: erstes Feld, zweites Feld, Knopf – dann den entstandenen Ablauf frisch abspielen."""
        self.site.logins = []
        secrets = {"email": "tester@example.de", "passwort": "sehr-geheim-42"}
        r = await self.open(path)
        lines = [f"öffne {self.base}{path}"]
        fields = [e for e in r["snapshot"]["elements"] if e["kind"] == "field"]
        self.assertEqual(len(fields), 2, r["snapshot"]["elements"])
        for el, name in zip(fields, ("email", "passwort")):
            ask = await self.live.act({"type": "pick", "mark": el["mark"]}, secrets)
            self.assertEqual(ask.get("need"), "text", ask)
            r = await self.live.act({"type": "fill", "target": {k: v for k, v in ask["target"].items()
                                                                if k in ("target", "near", "nth")},
                                     "text": "{" + name + "}"}, secrets)
            self.assertNotIn("error", r)
            lines += r["steps"]
        button = next(e for e in r["snapshot"]["elements"] if e["kind"] == "button")
        r = await self.live.act({"type": "pick", "mark": button["mark"]}, secrets)
        self.assertNotIn("error", r)
        lines += r["steps"]
        self.assertEqual(self.site.logins, [secrets])
        await self.live.close()
        self.live = __import__("flow_live").LiveSession()
        r = await self.live.open(fl.parse_steps("\n".join(lines), partial=True), secrets)
        self.assertIsNone(r["error"])
        self.assertEqual(self.site.logins, [secrets, secrets])
        return fields, lines

    async def test_kacheln_mit_langem_text_und_pfeil_ohne_text(self):
        self.site.visited = []
        for pick, expected in ((lambda els: next(e for e in els if e["label"].startswith("Web-Recherche")), "/modul/b"),
                               (lambda els: [e for e in els if e["kind"] == "link" and not e["label"]][0], "/modul/a/los")):
            r = await self.open("/kacheln")
            r = await self.live.act({"type": "pick", "mark": pick(r["snapshot"]["elements"])["mark"]}, {})
            self.assertNotIn("error", r)
            self.assertEqual(self.site.visited[-1], expected)
            # Abspielen trifft dasselbe Ziel
            await self.live.close()
            self.live = __import__("flow_live").LiveSession()
            await self.open("/kacheln", "\n".join(r["steps"]))
            self.assertEqual(self.site.visited[-1], expected)

    async def test_blaettern_im_inneren_bereich(self):
        r = await self.open("/kacheln")
        self.assertFalse(any(e["label"] == "Ganz unten" for e in r["snapshot"]["elements"]))
        r = await self.live.act({"type": "scroll", "x": 700, "y": 400, "dy": 3000}, {})
        self.assertEqual(r["steps"], [])
        button = next(e for e in r["snapshot"]["elements"] if e["label"] == "Ganz unten")
        r = await self.live.act({"type": "pick", "mark": button["mark"]}, {})
        self.assertEqual(r["steps"][0], 'klicke "Ganz unten"')

    async def test_anmeldung_ohne_beschriftung(self):
        fields, lines = await self.login_by_clicking("/ohne-beschriftung")
        self.assertEqual([f["label"] for f in fields], ["Benutzer", "Kennwort"])   # so sieht es ein Mensch
        self.assertTrue(all("sehr-geheim" not in line for line in lines))

    async def test_anmeldung_im_shadow_dom(self):
        await self.login_by_clicking("/shadow")

    async def test_anmeldung_im_iframe(self):
        fields, _ = await self.login_by_clicking("/eingebettet")
        self.assertTrue(all(f["box"]["y"] > 30 for f in fields))                   # Lage auf der Seite, nicht im Rahmen

    async def test_gleiche_knoepfe_werden_eindeutig_beschrieben(self):
        snap = (await self.open("/liste"))["snapshot"]
        marks = [e["mark"] for e in snap["elements"] if e["label"] == "Löschen"]
        self.assertEqual(len(marks), 4)
        got = []
        for mark in marks:
            r = await self.live.act({"type": "pick", "mark": mark}, {})
            got.append((r["steps"][0], r["snapshot"]))
            snap = r["snapshot"]
        self.assertEqual([s for s, _ in got], ['klicke "Löschen" bei "Bestellung 4711"', 'klicke "Löschen" bei "Bestellung 4712"',
                                               'klicke "Löschen" (Nr. 3)', 'klicke "Löschen" (Nr. 4)'])
        # … und beim Abspielen trifft jede Zeile wieder genau ihren Knopf
        for line, expect in zip([s for s, _ in got], ["4711", "4712", "a", "b"]):
            live = type(self.live)()
            try:
                await live.open(fl.parse_steps(f"öffne {self.base}/liste\n{line}", partial=True), {})
                self.assertEqual(await live.page.inner_text("#out"), f"weg: {expect}")
            finally:
                await live.close()

    async def test_scheiternder_schritt_wird_gezeigt(self):
        r = await self.open(lines='tippe in "E-Mail" {email}\ntippe in "Passwort" {passwort}\nklicke "Anmelden"\n'
                                  'warte auf Text "Willkommen"', email="tester@example.de", passwort="falsch")
        self.assertEqual(r["error"]["index"], 4)
        self.assertIn("Willkommen", r["error"]["message"])
        self.assertNotIn("falsch", r["error"]["message"])
        self.assertTrue(any(e["label"] == "Anmelden" for e in r["snapshot"]["elements"]))


# Seitenschutz wie per .htaccess: alles unter /geheim nur mit Benutzer und Passwort (HTTP Basic Auth)
SITE_AUTH = {"user": "admin", "password": "tür-zu-77"}
PROTECTED_PAGE = """<!doctype html><html lang="de"><body>
<h1>Intern</h1><button onclick="laden()">Laden</button><p id="out"></p>
<script>async function laden() {
  const d = await (await fetch('/geheim/daten')).json();
  document.getElementById('out').textContent = 'Fertig: ' + d.wert;
}</script></body></html>"""


class ProtectedSite(ChatSite):
    def __init__(self):
        super().__init__()
        self.authorized = 0
        self.expected = fl.basic_header(SITE_AUTH)

    async def handle(self, req):
        if req.path.startswith("/geheim/"):
            if req.headers.get("Authorization") != self.expected:
                return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="Intern"'})
            self.authorized += 1
            if req.path == "/geheim/start":
                return web.Response(text=PROTECTED_PAGE, content_type="text/html")
            if req.path == "/geheim/daten":
                return web.json_response({"wert": 42})
        return await super().handle(req)


@unittest.skipUnless(HAS_BROWSER, "Playwright/Chromium nicht installiert")
class Seitenschutz(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.site = ProtectedSite()
        self.base = await self.site.start()
        self.out = tempfile.mkdtemp()

    async def asyncTearDown(self):
        await self.site.runner.cleanup()

    async def vorfuehren(self, site_auth):
        import flow_live
        live = flow_live.LiveSession()
        try:
            return await live.open(fl.parse_steps(f"öffne {self.base}/geheim/start", partial=True), {}, site_auth)
        finally:
            await live.close()

    async def test_ohne_zugangsdaten_klare_meldung_statt_weisser_seite(self):
        with self.assertRaisesRegex(sw.lt.PreflightError, "401"):
            await self.vorfuehren(None)
        with self.assertRaisesRegex(sw.lt.PreflightError, "Seitenschutz"):
            await self.vorfuehren({"user": "admin", "password": "falsch"})

    async def test_vorfuehren_mit_zugangsdaten(self):
        r = await self.vorfuehren(SITE_AUTH)
        self.assertIsNone(r["error"])
        self.assertEqual([e["label"] for e in r["snapshot"]["elements"]], ["Laden"])

    async def test_aufzeichnen_und_abspielen_mit_zugangsdaten(self):
        steps = f'öffne {self.base}/geheim/start\nmessen ab hier\nklicke "Laden"\nwarte auf Text "Fertig: 42"'
        args = sw.build_args({"kind": "flow", "confirm_owner": True, "steps": steps, "site_auth": SITE_AUTH,
                              "levels": "1,2", "level_seconds": 1, "warmup_seconds": 0, "min_samples": 2,
                              "baseline_requests": 2, "cooldown": 0, "spike_idle": 0, "tests": "baseline,ramp"})
        st = fl.FlowStressTest(args, self.out)
        before = self.site.authorized
        await st.run()
        self.assertEqual(st.summary["baseline"]["errors"], 0)
        self.assertGreaterEqual(self.site.authorized - before, 2 + 2 + 2)   # Seite + Daten beim Aufzeichnen, dann je Lauf
        self.assertNotIn("site_auth", st.summary["config"])
        for name in os.listdir(self.out):
            if name.endswith(".png"):
                continue
            with open(os.path.join(self.out, name), encoding="utf-8", errors="replace") as f:
                content = f.read()
            for secret in ("tür-zu-77", self.site.expected.split()[1]):
                self.assertNotIn(secret, content, name)

    def test_zugangsdaten_werden_geprueft(self):
        base = {"kind": "flow", "confirm_owner": True, "steps": "öffne http://x.test/\nmessen ab hier\nklicke \"Los\""}
        self.assertIsNone(sw.build_args({**base, "site_auth": {"user": "", "password": ""}}).site_auth)
        for bad in ({"user": "a:b", "password": "x"}, {"user": "", "password": "x"}, {"user": "a"}, "admin:x"):
            with self.assertRaises(ValueError):
                sw.build_args({**base, "site_auth": bad})


if __name__ == "__main__":
    unittest.main()
