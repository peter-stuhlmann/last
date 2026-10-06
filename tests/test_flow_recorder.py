"""Aufzeichnen mit echtem Browser und anschließendes Abspielen – braucht Chromium (im Docker-Image enthalten)."""
import asyncio
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
            await asyncio.sleep(0.1)
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


if __name__ == "__main__":
    unittest.main()
