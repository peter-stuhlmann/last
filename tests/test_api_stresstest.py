"""Tests für den Lasttest von HTTP-APIs."""
import asyncio
import json
import os
import sys
import tempfile
import unittest

from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_report_web import all_text, page, sample  # noqa: E402

import report_web as rw  # noqa: E402
import stresstest_web as sw  # noqa: E402
import web_stresstest as ws  # noqa: E402


class Api:
    """Kleine API zum Testen: GET /items, POST /items (nur mit Token), GET /kaputt."""

    def __init__(self):
        self.calls = []

    async def handle(self, req):
        body = await req.text()
        self.calls.append({"method": req.method, "path": req.path, "headers": dict(req.headers), "body": body})
        await asyncio.sleep(0.005)
        if req.path == "/kaputt":
            return web.json_response({"error": "boom"}, status=500)
        if req.path == "/weiter":
            raise web.HTTPFound("/items")
        if req.method == "POST":
            if req.headers.get("X-Token") != "geheim":
                return web.json_response({"error": "kein Zugriff"}, status=401)
            return web.json_response({"id": len(self.calls)}, status=201)
        return web.json_response({"items": [1, 2, 3]})

    async def start(self):
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        return f"http://127.0.0.1:{self.runner.addresses[0][1]}"


def make_args(url, **over):
    cfg = {"kind": "api", "base_url": url, "confirm_owner": True, "levels": "1,2", "level_seconds": 1,
           "warmup_seconds": 0, "min_samples": 2, "baseline_requests": 2, "rate_seconds": 1,
           "spike_size": 3, "soak_minutes": 0.02, "cooldown": 0, "spike_idle": 0,
           "tests": "baseline,ramp,rate,spike,soak", **over}
    return sw.build_args(cfg)


class Eingaben(unittest.TestCase):
    def test_nur_mit_bestaetigung(self):
        with self.assertRaisesRegex(ValueError, "bestätig"):
            sw.build_args({"kind": "api", "base_url": "http://api.example/items"})

    def test_standardwerte(self):
        a = make_args("http://api.example/items")
        self.assertEqual((a.kind, a.method, a.expect_status, a.slo_load), ("api", "GET", "2xx", 0.5))
        self.assertFalse(a.include_assets)

    def test_kopfzeilen_und_body(self):
        a = make_args("http://api.example/items", method="post", body='{"a": 1}',
                      headers=[{"name": "X-Token", "value": "geheim"}], expect_status="201", slo_load="0.2")
        self.assertEqual(a.method, "POST")
        self.assertEqual(a.headers, {"X-Token": "geheim"})
        self.assertEqual(a.body, '{"a": 1}')
        self.assertEqual(a.expect_status, "201")
        self.assertEqual(a.slo_load, 0.2)

    def test_gefaehrliche_eingaben_werden_abgelehnt(self):
        bad = [
            {"method": "TRACE"},
            {"headers": [{"name": "Host", "value": "intern"}]},
            {"headers": [{"name": "X-A", "value": "a\r\nX-B: b"}]},
            {"headers": [{"name": "X A", "value": "a"}]},
            {"headers": [{"name": f"X-{i}", "value": "a"} for i in range(40)]},
            {"body": "x" * 70000},
            {"expect_status": "alles"},
        ]
        for over in bad:
            with self.assertRaises(ValueError, msg=str(over)[:60]):
                make_args("http://api.example/items", **over)

    def test_status_erwartung(self):
        self.assertTrue(ws.status_ok(204, "2xx"))
        self.assertFalse(ws.status_ok(301, "2xx"))
        self.assertTrue(ws.status_ok(201, "201"))
        self.assertFalse(ws.status_ok(200, "201"))


class ApiClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = Api()
        self.url = await self.api.start()

    async def asyncTearDown(self):
        await self.api.runner.cleanup()

    async def test_get(self):
        async with ws.ApiClient(make_args(self.url + "/items")) as client:
            info = await client.prepare()
            r = await client.request(None, 0)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["requests"], 1)
        self.assertGreater(r["ttft"], 0)
        self.assertEqual(info["status"], 200)
        self.assertIn("LAST-Lasttest", self.api.calls[0]["headers"]["User-Agent"])

    async def test_post_mit_kopfzeile_und_body(self):
        args = make_args(self.url + "/items", method="POST", body='{"name": "x"}',
                         headers=[{"name": "X-Token", "value": "geheim"}], expect_status="201")
        async with ws.ApiClient(args) as client:
            await client.prepare()
            r = await client.request(None, 0)
        self.assertTrue(r["ok"], r)
        call = self.api.calls[-1]
        self.assertEqual((call["method"], call["body"]), ("POST", '{"name": "x"}'))
        self.assertEqual(call["headers"]["Content-Type"], "application/json")

    async def test_falscher_status_bricht_vor_dem_test_ab(self):
        args = make_args(self.url + "/items", method="POST", body="{}")       # ohne Token → 401
        async with ws.ApiClient(args) as client:
            with self.assertRaisesRegex(ws.lt.PreflightError, "401"):
                await client.prepare()

    async def test_fehler_unter_last_zaehlen(self):
        async with ws.ApiClient(make_args(self.url + "/items")) as client:
            await client.prepare()
            client.url = self.url + "/kaputt"
            r = await client.request(None, 0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "http_500")

    async def test_folgt_keinen_weiterleitungen(self):
        async with ws.ApiClient(make_args(self.url + "/weiter", expect_status="302")) as client:
            await client.prepare()
            r = await client.request(None, 0)
        self.assertTrue(r["ok"])
        self.assertNotIn("/items", [c["path"] for c in self.api.calls])

    async def test_ganzer_lauf_ohne_geheimnisse_im_ergebnis(self):
        out = tempfile.mkdtemp()
        args = make_args(self.url + "/items", method="POST", body='{"passwort": "hunter2"}',
                         headers=[{"name": "X-Token", "value": "geheim"}], expect_status="201", target_users=600)
        st = ws.WebStressTest(args, out)
        await st.run()
        s = st.summary
        self.assertEqual(s["config"]["kind"], "api")
        self.assertEqual(s["config"]["method"], "POST")
        self.assertEqual(s["config"]["header_names"], ["X-Token"])
        self.assertEqual(s["config"]["body_bytes"], len('{"passwort": "hunter2"}'))
        for key in ("baseline", "ramp", "rate", "spike", "soak", "control", "quality"):
            self.assertIn(key, s, key)
        # Kopfzeilen-Werte und Body dürfen nirgends auf der Platte landen
        for name in os.listdir(out):
            with open(os.path.join(out, name), encoding="utf-8", errors="replace") as f:
                content = f.read()
            self.assertNotIn("geheim", content, name)
            self.assertNotIn("hunter2", content, name)
        with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["config"]["kind"], "api")


def api_sample(**over):
    """Ein vollständiger API-Lauf: gleiche Form wie ein Website-Lauf, andere Bedeutung."""
    s = sample()
    s["config"].update({"kind": "api", "base_url": "https://api.example/v1/items", "method": "GET",
                        "expect_status": "2xx", "slo_load": 0.5, "target_users": 1000,
                        "header_names": ["Authorization"], "body_bytes": 0, "include_assets": False})
    s["prechecks"] = {"status": 200, "bytes": 1200, "assets": 0, "total_bytes": 1200, "files": [],
                      "final_url": "https://api.example/v1/items", "rtt_ms": 40.0, "busy": None}
    fast = dict(ttft_p50=0.04, ttft_p95=0.06, e2e_p50=0.05, e2e_p95=0.08, e2e_mean=0.055, e2e_max=0.2)
    s["baseline"] = page(**fast)
    for st, p95 in zip(s["ramp"]["steps"], (0.08, 0.2, 0.4, 1.3)):
        st.update(fast)
        st["e2e_p95"] = p95
    for stage in s["rate"]["stages"]:
        stage.update(fast)
    for part in (s["spike"]["burst"], s["spike"]["recovery"], s["soak"]["total"], s["control"]["s"]):
        part.update(fast)
    s.update(over)
    return s


class Aussagen(unittest.TestCase):
    def test_kapazitaet_in_anfragen_pro_minute(self):
        cap = ws.capacity(api_sample())
        self.assertEqual(cap["users"], 1500.0)          # 25 Anfragen/s flüssig = 1.500 pro Minute
        self.assertEqual(cap["source"], "rate")
        self.assertEqual(cap["rec_concurrency"], 32)

    def test_urteil_spricht_von_anfragen(self):
        v = ws.verdict(api_sample())
        self.assertEqual(v["status"], "good")
        self.assertEqual(v["headline"], "Die API hält der Last stand.")
        self.assertIn("1.500 Anfragen pro Minute", v["reasons"][0][1])
        self.assertNotIn("Besucher", json.dumps(v, ensure_ascii=False))
        s = api_sample()
        s["config"]["target_users"] = 9000
        self.assertEqual(ws.verdict(s)["status"], "bad")

    def test_bericht_ohne_website_begriffe(self):
        d = tempfile.mkdtemp()
        s = api_sample()
        rw.build_report(s, os.path.join(d, "b.pptx"))
        rw.build_pdf(s, os.path.join(d, "b.pdf"))
        rw.build_compare([s, api_sample()], os.path.join(d, "v.pptx"), ["vorher", "nachher"])
        for name in ("b.pptx", "v.pptx"):
            text = all_text(os.path.join(d, name))
            for forbidden in ("Besucher", "Website", "Seite ", "Browser", "Ladezeit", "Token"):
                self.assertNotIn(forbidden, text, f"{name}: {forbidden}")
            self.assertNotRegex(text, r"\b(None|nan)\b")
        text = all_text(os.path.join(d, "b.pptx"))
        for expected in ("Wie viele Anfragen hält unsere API aus?", "https://api.example/v1/items",
                         "Die API hält der Last stand.", "Anfragen pro Minute", "Antwortzeit", "GET"):
            self.assertIn(expected, text)

    def test_website_bericht_bleibt_wie_er_war(self):
        path = os.path.join(tempfile.mkdtemp(), "b.pptx")
        rw.build_report(sample(), path)
        text = all_text(path)
        self.assertIn("Wie viele Besucher hält unsere Website aus?", text)
        self.assertNotIn("API", text)

    def test_vergleich_nur_gleicher_art(self):
        self.assertIs(sw.comparison_builder(["api", "api"]), rw.build_comparison)
        with self.assertRaisesRegex(ValueError, "gleicher Art"):
            sw.comparison_builder(["api", "web"])


if __name__ == "__main__":
    unittest.main()
