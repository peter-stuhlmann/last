# -*- coding: utf-8 -*-
"""Tests für den Website-Lasttest. Starten (im Projektordner):

    docker run --rm -v "$PWD":/src -w /src llm-stresstest python -m unittest discover -s tests -v
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest

from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stresstest_web as sw  # noqa: E402
import web_stresstest as ws  # noqa: E402

PAGE = b"""<!doctype html><html><head><title>Testseite</title>
<link rel="stylesheet" href="/style.css">
<link rel="preconnect" href="https://fremd.example">
<script src="app.js"></script>
<script src="https://fremd.example/tracker.js"></script>
</head><body><img src="/bild.png"><img src="data:image/png;base64,AAAA">
<a href="/andere-seite">Link</a></body></html>"""


class Site:
    """Kleine Website zum Testen; zählt die Aufrufe und kann Fehler liefern."""

    def __init__(self):
        self.hits = {}
        self.fail = False
        self.agents = set()

    async def handle(self, req):
        self.hits[req.path] = self.hits.get(req.path, 0) + 1
        self.agents.add(req.headers.get("User-Agent", ""))
        if self.fail:
            return web.Response(status=503, text="ueberlastet")
        await asyncio.sleep(0.005)
        if req.path == "/":
            return web.Response(body=PAGE, content_type="text/html")
        if req.path in ("/style.css", "/app.js", "/bild.png"):
            return web.Response(body=b"x" * 1000)
        return web.Response(status=404)

    async def start(self):
        app = web.Application()
        app.router.add_get("/{tail:.*}", self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = self.runner.addresses[0][1]
        return f"http://127.0.0.1:{port}/"


def make_args(url, **over):
    cfg = {"kind": "web", "base_url": url, "confirm_owner": True, "levels": "1,2", "level_seconds": 1,
           "warmup_seconds": 0, "min_samples": 2, "baseline_requests": 2, "rate_seconds": 1,
           "spike_size": 3, "soak_minutes": 0.02, "tests": "baseline,ramp,rate,spike,soak", **over}
    return sw.build_args(cfg)


class ParseAssets(unittest.TestCase):
    def test_nur_dateien_derselben_website(self):
        assets = ws.find_assets(PAGE.decode(), "http://shop.example/")
        self.assertEqual(sorted(assets), ["http://shop.example/app.js", "http://shop.example/bild.png",
                                          "http://shop.example/style.css"])

    def test_begrenzt_die_anzahl(self):
        html = "".join(f'<img src="/b{i}.png">' for i in range(500))
        self.assertEqual(len(ws.find_assets(html, "http://shop.example/")), ws.MAX_ASSETS)


class BuildArgs(unittest.TestCase):
    def test_website_nur_mit_bestaetigung(self):
        with self.assertRaisesRegex(ValueError, "bestätig"):
            sw.build_args({"kind": "web", "base_url": "http://shop.example/"})

    def test_website_argumente(self):
        a = make_args("http://shop.example/", slo_load="2.5", include_assets=False)
        self.assertEqual(a.kind, "web")
        self.assertEqual(a.slo_load, 2.5)
        self.assertFalse(a.include_assets)
        self.assertNotIn("context", a.tests)

    def test_ki_server_bleibt_wie_bisher(self):
        a = sw.build_args({"base_url": "http://spark:8000/v1"})
        self.assertEqual(a.kind, "llm")

    def test_unbekannte_art(self):
        with self.assertRaises(ValueError):
            sw.build_args({"kind": "ftp", "base_url": "http://x/"})


class WebClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.site = Site()
        self.url = await self.site.start()

    async def asyncTearDown(self):
        await self.site.runner.cleanup()

    async def test_seitenaufruf_laedt_seite_und_dateien(self):
        async with ws.WebClient(make_args(self.url)) as client:
            await client.prepare()
            r = await client.request(None, 0)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["requests"], 4)          # Seite + 3 Dateien
        self.assertGreater(r["bytes"], 3000)
        self.assertGreater(r["ttft"], 0)
        self.assertGreaterEqual(r["e2e"], r["ttft"])
        self.assertNotIn("/andere-seite", self.site.hits)
        self.assertTrue(all("LAST-Lasttest" in a for a in self.site.agents))

    async def test_ohne_dateien(self):
        async with ws.WebClient(make_args(self.url, include_assets=False)) as client:
            await client.prepare()
            r = await client.request(None, 0)
        self.assertEqual(r["requests"], 1)

    async def test_fehlerseite_zaehlt_als_fehler(self):
        async with ws.WebClient(make_args(self.url)) as client:
            await client.prepare()
            self.site.fail = True
            r = await client.request(None, 0)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "http_503")

    async def test_nicht_erreichbar(self):
        async with ws.WebClient(make_args("http://127.0.0.1:9/")) as client:
            with self.assertRaises(ws.lt.PreflightError):
                await client.prepare()


class Kennzahlen(unittest.TestCase):
    def result(self, ok=True, ttft=0.1, e2e=0.5, start=0.0, **kw):
        return {"ok": ok, "ttft": ttft if ok else None, "e2e": e2e, "tp_start": start, "bytes": 1000,
                "requests": 4, "error": None if ok else "http_503", **kw}

    def test_zusammenfassung(self):
        s = ws.summarize([self.result(), self.result(e2e=1.5), self.result(ok=False)], 2.0)
        self.assertEqual((s["n"], s["ok"], s["errors"]), (3, 2, 1))
        self.assertAlmostEqual(s["error_rate"], 1 / 3)
        self.assertEqual(s["req_s"], 1.0)             # 2 Seiten in 2 Sekunden
        self.assertEqual(s["e2e_mean"], 1.0)
        self.assertEqual(s["bytes_s"], 1000.0)
        self.assertEqual(s["error_types"], {"http_503": 1})
        self.assertIsNone(s["out_tps"])

    def test_ziel(self):
        cfg = {"slo_load": 1.0}
        self.assertTrue(ws.meets_slo({"error_rate": 0, "e2e_p95": 0.9}, cfg))
        self.assertFalse(ws.meets_slo({"error_rate": 0, "e2e_p95": 1.2}, cfg))
        self.assertFalse(ws.meets_slo({"error_rate": 0.1, "e2e_p95": 0.5}, cfg))
        self.assertFalse(ws.meets_slo({"error_rate": 0, "e2e_p95": None}, cfg))

    def test_kapazitaet_und_urteil(self):
        step = {"concurrency": 8, "error_rate": 0, "e2e_p95": 0.8, "e2e_mean": 0.5, "req_s": 10.0}
        summary = {"config": {"slo_load": 1.0, "think_time": 30, "target_users": 200},
                   "ramp": {"steps": [step, {**step, "concurrency": 16, "e2e_p95": 3.0}]}}
        cap = ws.capacity(summary)
        self.assertEqual(cap["rec_concurrency"], 8)
        self.assertEqual(cap["users"], 305.0)         # 10 Seiten/s × (0,5 s + 30 s)
        self.assertEqual(cap["source"], "ramp")
        self.assertEqual(ws.verdict(summary)["status"], "good")
        summary["config"]["target_users"] = 1000
        v = ws.verdict(summary)
        self.assertEqual(v["status"], "bad")
        self.assertIn("Besucher", v["reasons"][0][1])


class GanzerLauf(unittest.IsolatedAsyncioTestCase):
    async def test_kurzer_lauf_liefert_alle_ergebnisse(self):
        site = Site()
        url = await site.start()
        out = tempfile.mkdtemp()
        try:
            args = make_args(url, cooldown=0, spike_idle=0, target_users=5)
            st = ws.WebStressTest(args, out)
            updates = []
            st.on_update = lambda: updates.append(1)
            await st.run()
        finally:
            await site.runner.cleanup()
        s = st.summary
        self.assertEqual(s["config"]["kind"], "web")
        self.assertNotIn("confirm_owner", s["config"])
        for key in ("prechecks", "baseline", "ramp", "rate", "spike", "soak", "control",
                    "capacity", "verdict"):
            self.assertIn(key, s, key)
        self.assertEqual(s["prechecks"]["assets"], 3)
        self.assertEqual([x["concurrency"] for x in s["ramp"]["steps"]], [1, 2])
        self.assertGreater(s["ramp"]["steps"][0]["req_s"], 0)
        self.assertIsNone(s["meta"]["current_test"])
        self.assertIsNone(s["probes"])
        self.assertIsNone(s["economics"])
        self.assertTrue(updates)
        with open(os.path.join(out, "summary.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["config"]["kind"], "web")


if __name__ == "__main__":
    unittest.main()
