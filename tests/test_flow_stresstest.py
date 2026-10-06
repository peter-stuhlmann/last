"""Tests für Abläufe: Schritt-Sprache, Erkennen veränderlicher Werte, Abspielen per HTTP.
Der Rekorder mit echtem Browser steht in test_flow_recorder.py (braucht Chromium)."""
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

STEPS = """
öffne https://app.example/login
tippe in "E-Mail" {email}
tippe in "Passwort" {passwort}
klicke "Anmelden"
warte auf Text "Willkommen"
öffne https://app.example/chat
── messen ab hier ──
tippe in "Nachricht" "Was ist ein Lasttest?"
drücke Enter
warte auf erste Antwort in ".antwort"
warte bis ".antwort" fertig ist (2 s ruhig)
"""


class SchrittSprache(unittest.TestCase):
    def test_liest_alle_schrittarten(self):
        steps = fl.parse_steps(STEPS)
        self.assertEqual([s["kind"] for s in steps], [
            "open", "fill", "fill", "click", "wait_text", "open", "measure",
            "fill", "press", "wait_first", "wait_done"])
        self.assertEqual(steps[1]["target"], "E-Mail")
        self.assertEqual(steps[1]["text"], "{email}")
        self.assertEqual(steps[7]["text"], "Was ist ein Lasttest?")
        self.assertEqual(steps[8]["key"], "Enter")
        self.assertEqual(steps[10]["target"], ".antwort")
        self.assertEqual(steps[10]["quiet"], 2.0)
        self.assertEqual(steps[0]["line"], 2)

    def test_platzhalter(self):
        self.assertEqual(fl.placeholders(fl.parse_steps(STEPS)), ["email", "passwort"])
        self.assertEqual(fl.fill_text("Hallo {name}!", {"name": "Ada"}), "Hallo Ada!")
        with self.assertRaisesRegex(ValueError, "name"):
            fl.fill_text("Hallo {name}!", {})

    def test_meldet_unbekannte_zeilen_mit_nummer(self):
        with self.assertRaisesRegex(ValueError, "Zeile 2"):
            fl.parse_steps("öffne https://x/\nhüpfe dreimal")
        with self.assertRaisesRegex(ValueError, "http"):
            fl.parse_steps("öffne javascript:alert(1)")
        with self.assertRaisesRegex(ValueError, "messen"):
            fl.parse_steps("öffne https://x/\nmessen ab hier\nmessen ab hier")

    def test_braucht_messbereich_und_start(self):
        with self.assertRaisesRegex(ValueError, "messen"):
            fl.parse_steps("öffne https://x/\nklicke \"Los\"")
        with self.assertRaisesRegex(ValueError, "öffne"):
            fl.parse_steps("klicke \"Los\"\nmessen ab hier\nklicke \"Senden\"")
        with self.assertRaisesRegex(ValueError, "Nach „messen"):
            fl.parse_steps("öffne https://x/\nmessen ab hier")

    def test_selektor_oder_sichtbarer_text(self):
        self.assertTrue(fl.is_selector("#chat-input"))
        self.assertTrue(fl.is_selector("[data-testid=send]"))
        self.assertTrue(fl.is_selector("div.antwort > p"))
        self.assertFalse(fl.is_selector("Nachricht"))
        self.assertFalse(fl.is_selector("Jetzt anmelden"))


def rec(i, method, url, status=200, body=None, resp=None, headers=None, resp_headers=None, stream=False):
    return {"i": i, "method": method, "url": url, "headers": headers or {}, "body": body, "status": status,
            "resp_headers": resp_headers or {}, "resp_body": resp, "t_start": i * 1.0, "t_headers": i + 0.1,
            "t_end": i + 0.5, "stream": stream, "resource_type": "fetch"}


class VeraenderlicheWerte(unittest.TestCase):
    def test_erkennt_id_aus_frueherer_antwort(self):
        cid = str(uuid.uuid4())
        records = [
            rec(0, "POST", "https://app.example/api/conversations", 201, body="{}",
                resp=json.dumps({"data": {"id": cid, "title": "neu"}})),
            rec(1, "POST", f"https://app.example/api/conversations/{cid}/messages", 200,
                body=json.dumps({"conversation": cid, "text": "Hallo"}), resp="data: hi\n\n",
                resp_headers={"content-type": "text/event-stream"}, stream=True),
        ]
        plan = fl.build_plan(records)
        self.assertEqual(plan["main"], 1)
        tpl = plan["requests"][1]
        self.assertNotIn(cid, tpl["url"])
        self.assertNotIn(cid, tpl["body"])
        self.assertEqual(len(plan["extract"]), 1)
        var, source = next(iter(plan["extract"].items()))
        self.assertEqual(source, {"from": 0, "path": ["data", "id"]})
        self.assertIn("{{" + var + "}}", tpl["url"])
        self.assertIn("{{" + var + "}}", tpl["body"])
        self.assertEqual(fl.render("x/{{v}}/y", {"v": "7"}), "x/7/y")

    def test_laesst_feste_werte_in_ruhe(self):
        records = [rec(0, "GET", "https://app.example/api/me", resp=json.dumps({"id": "benutzer-12345678"})),
                   rec(1, "POST", "https://app.example/api/chat", body=json.dumps({"modell": "standard-modell"}))]
        plan = fl.build_plan(records)
        self.assertEqual(plan["extract"], {})
        self.assertIn("standard-modell", plan["requests"][1]["body"])

    def test_hauptanfrage_ist_der_strom_oder_die_laengste(self):
        records = [rec(0, "GET", "https://app.example/api/a"), rec(1, "GET", "https://app.example/api/b")]
        records[0]["t_end"] = 3.0
        self.assertEqual(fl.build_plan(records)["main"], 0)

    def test_schreibt_keine_geheimnisse_in_die_kurzfassung(self):
        records = [rec(0, "POST", "https://app.example/api/chat?token=geheim123456", body='{"pw": "hunter2hunter2"}',
                      headers={"Authorization": "Bearer abcdefghijklmnop", "Cookie": "sid=xyz12345678"})]
        public = fl.public_plan(fl.build_plan(records))
        text = json.dumps(public)
        for secret in ("geheim123456", "hunter2hunter2", "abcdefghijklmnop", "xyz12345678"):
            self.assertNotIn(secret, text)
        self.assertEqual(public[0]["method"], "POST")
        self.assertEqual(public[0]["path"], "/api/chat")
        self.assertIn("Authorization", public[0]["header_names"])


class ChatApp:
    """Nachbau einer Chat-Anwendung: Login setzt ein Cookie, POST /api/conversations liefert eine ID,
    POST /api/conversations/{id}/messages streamt die Antwort."""

    def __init__(self):
        self.calls = []
        self.known = set()

    async def login(self, req):
        resp = web.json_response({"ok": True})
        resp.set_cookie("sid", "sitzung-123456789")
        return resp

    async def conversations(self, req):
        if req.cookies.get("sid") != "sitzung-123456789":
            return web.json_response({"error": "kein Zugriff"}, status=401)
        cid = str(uuid.uuid4())
        self.known.add(cid)
        self.calls.append(("conversations", None))
        return web.json_response({"data": {"id": cid}}, status=201)

    async def messages(self, req):
        cid = req.match_info["cid"]
        self.calls.append(("messages", cid))
        if cid not in self.known:
            return web.json_response({"error": "unbekannt"}, status=404)
        await req.json()
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(req)
        await asyncio.sleep(0.05)                       # „Nachdenken“ vor dem ersten Wort
        for word in ("Ein", "Lasttest", "prüft", "die", "Belastbarkeit."):
            await resp.write(f"data: {word}\n\n".encode())
            await asyncio.sleep(0.01)
        await resp.write(b"data: [DONE]\n\n")
        return resp

    async def start(self):
        app = web.Application()
        app.router.add_post("/login", self.login)
        app.router.add_post("/api/conversations", self.conversations)
        app.router.add_post("/api/conversations/{cid}/messages", self.messages)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        return f"http://127.0.0.1:{self.runner.addresses[0][1]}"


def recorded_plan(base):
    """So sähe die Aufzeichnung eines Chat-Durchlaufs aus."""
    cid = "11111111-2222-3333-4444-555555555555"
    records = [
        rec(0, "POST", f"{base}/api/conversations", 201, body="{}", resp=json.dumps({"data": {"id": cid}}),
            headers={"Content-Type": "application/json", "Cookie": "sid=sitzung-123456789"}),
        rec(1, "POST", f"{base}/api/conversations/{cid}/messages", 200,
            body=json.dumps({"text": "Was ist ein Lasttest?"}), resp="data: Ein\n\n",
            headers={"Content-Type": "application/json", "Cookie": "sid=sitzung-123456789"},
            resp_headers={"content-type": "text/event-stream"}, stream=True),
    ]
    plan = fl.build_plan(records)
    plan["cookies"] = [{"name": "sid", "value": "sitzung-123456789", "domain": "127.0.0.1", "path": "/"}]
    return plan


class Abspielen(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = ChatApp()
        self.base = await self.app.start()

    async def asyncTearDown(self):
        await self.app.runner.cleanup()

    async def test_spielt_den_ablauf_mit_neuer_id_ab(self):
        args = sw.build_args({"kind": "flow", "base_url": self.base, "confirm_owner": True,
                              "steps": f"öffne {self.base}/\nmessen ab hier\nklicke \"Senden\""})
        async with fl.FlowClient(args, recorded_plan(self.base)) as client:
            r1 = await client.request(None, 0)
            await client.request(None, 0)
        self.assertTrue(r1["ok"], r1)
        self.assertEqual(r1["requests"], 2)
        self.assertGreater(r1["ttft"], 0.05)            # erstes Wort erst nach dem „Nachdenken“
        self.assertGreater(r1["e2e"], r1["ttft"])
        self.assertGreaterEqual(r1["chunks"], 5)
        ids = [cid for kind, cid in self.app.calls if kind == "messages"]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])             # jede Wiederholung holt sich ihre eigene ID
        self.assertTrue(all(i in self.app.known for i in ids))

    async def test_fehler_zaehlen(self):
        plan = recorded_plan(self.base)
        plan["cookies"] = []                            # ohne Sitzung: 401
        args = sw.build_args({"kind": "flow", "base_url": self.base, "confirm_owner": True,
                              "steps": f"öffne {self.base}/\nmessen ab hier\nklicke \"Senden\""})
        async with fl.FlowClient(args, plan) as client:
            r = await client.request(None, 0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "http_401")


class Eingaben(unittest.TestCase):
    def test_ablauf_argumente(self):
        a = sw.build_args({"kind": "flow", "base_url": "https://app.example/login", "confirm_owner": True,
                           "steps": STEPS, "secrets": {"email": "a@b.de", "passwort": "geheim"}, "slo_load": 8})
        self.assertEqual(a.kind, "flow")
        self.assertEqual(len(a.steps), 11)
        self.assertEqual(a.secrets, {"email": "a@b.de", "passwort": "geheim"})
        self.assertEqual(a.slo_load, 8.0)
        self.assertEqual(a.levels, "1,2,4,8,16,32")

    def test_fehlende_platzhalter(self):
        with self.assertRaisesRegex(ValueError, "passwort"):
            sw.build_args({"kind": "flow", "base_url": "https://app.example/login", "confirm_owner": True,
                           "steps": STEPS, "secrets": {"email": "a@b.de"}})

    def test_geheimnisse_bleiben_aus_der_konfiguration(self):
        a = sw.build_args({"kind": "flow", "base_url": "https://app.example/login", "confirm_owner": True,
                           "steps": STEPS, "secrets": {"email": "a@b.de", "passwort": "geheim"}})
        st = fl.FlowStressTest(a, tempfile.mkdtemp())
        st.raw.close()
        text = json.dumps(st.summary["config"], default=str)
        self.assertNotIn("geheim", text)
        self.assertNotIn("a@b.de", text)
        self.assertIn("tippe in", st.summary["config"]["steps_text"])
        self.assertEqual(st.summary["config"]["placeholders"], ["email", "passwort"])


if __name__ == "__main__":
    unittest.main()


class OhneBrowser(unittest.TestCase):
    def test_start_ohne_browser_wird_klar_abgelehnt(self):
        import unittest.mock as mock
        with mock.patch.dict(sw.FEATURES, {"flow": False}):
            with self.assertRaisesRegex(ValueError, "keinen Browser"):
                sw.check_features({"kind": "flow", "confirm_owner": True, "steps": "öffne http://x.test/"})
            sw.check_features({"kind": "web"})                 # andere Arten gehen weiter
