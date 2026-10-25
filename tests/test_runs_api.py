"""Läufe verwalten: Titel/Tags/Notiz je Lauf, Löschen in den Papierkorb, Liste mit Trend-Kennzahlen."""
import json
import os
import sys
import tempfile
import time
import unittest

from aiohttp.test_utils import AioHTTPTestCase

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_report_web import sample  # noqa: E402

import stresstest_web as sw  # noqa: E402


def make_run(root, name, **over):
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    s = sample()
    s["capacity"] = {"think_time": 30, "rec_concurrency": 32, "rate_ok": 25, "users": 766, "source": "rate"}
    s["verdict"] = {"status": "good", "headline": "ok", "reasons": []}
    for k, v in over.items():
        s[k] = v
    with open(os.path.join(path, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(s, f)
    return path


class LaeufeVerwalten(AioHTTPTestCase):
    async def get_application(self):
        self.root = tempfile.mkdtemp()
        make_run(self.root, "results_20261001_080000")
        make_run(self.root, "results_20261005_100000", meta={"started": "2026-10-05T10:00:00"})
        return sw.make_app(self.root)

    async def test_notizen_schreiben_und_in_der_liste_sehen(self):
        body = {"title": "Vor dem Cache", "tags": ["Shop", "prod-nah", "shop"], "note": "Erster Lauf nach dem Umbau.", "pinned": True}
        r = await self.client.put("/api/runs/results_20261005_100000/notes", json=body)
        self.assertEqual(r.status, 200, await r.text())
        saved = await r.json()
        self.assertEqual(saved["tags"], ["shop", "prod-nah"])          # kleingeschrieben, ohne Doppelte
        self.assertTrue(saved["updated"])
        with open(os.path.join(self.root, "results_20261005_100000", "notes.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["title"], "Vor dem Cache")
        runs = (await (await self.client.get("/api/runs")).json())["runs"]
        first = runs[0]
        self.assertEqual(first["name"], "results_20261005_100000")
        self.assertEqual(first["title"], "Vor dem Cache")
        self.assertTrue(first["pinned"])
        # Kennzahlen für den Trend kommen mit
        self.assertEqual(first["users"], 766)
        self.assertEqual(first["status"], "good")
        self.assertAlmostEqual(first["alone"], 0.6)
        self.assertEqual(first["target_users"], 500)
        self.assertEqual(runs[1]["title"], None)
        self.assertEqual(runs[1]["tags"], [])

    async def test_notizen_werden_geprueft(self):
        bad = [{"title": "x" * 81}, {"tags": ["a b"]}, {"tags": [f"t{i}" for i in range(11)]}, {"note": "n" * 2001},
               {"title": "zeile\numbruch"}, {"pinned": "ja"}, ["liste"]]
        for body in bad:
            r = await self.client.put("/api/runs/results_20261001_080000/notes", json=body)
            self.assertEqual(r.status, 400, body)
        r = await self.client.put("/api/runs/results_gibtsnicht/notes", json={"title": "x"})
        self.assertEqual(r.status, 404)
        r = await self.client.put("/api/runs/..%2F..%2Fetc/notes", json={"title": "x"})
        self.assertEqual(r.status, 404)

    async def test_loeschen_legt_in_den_papierkorb(self):
        r = await self.client.delete("/api/runs/results_20261001_080000")
        self.assertEqual(r.status, 200, await r.text())
        self.assertFalse(os.path.exists(os.path.join(self.root, "results_20261001_080000")))
        trash = os.path.join(self.root, sw.TRASH_DIR)
        self.assertEqual(len(os.listdir(trash)), 1)
        names = [x["name"] for x in (await (await self.client.get("/api/runs")).json())["runs"]]
        self.assertEqual(names, ["results_20261005_100000"])
        self.assertEqual((await self.client.delete("/api/runs/results_20261001_080000")).status, 404)
        self.assertEqual((await self.client.delete("/api/runs/results_x%2F..%2Fx")).status, 404)

    async def test_papierkorb_wird_nach_sieben_tagen_geleert(self):
        trash = os.path.join(self.root, sw.TRASH_DIR)
        old, new = os.path.join(trash, "alt"), os.path.join(trash, "neu")
        os.makedirs(old)
        os.makedirs(new)
        past = time.time() - 8 * 86400
        os.utime(old, (past, past))
        sw.empty_trash(self.root)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))

    async def test_laufender_lauf_ist_nicht_loeschbar(self):
        runner = self.app["runner"]
        runner.outdir = os.path.join(self.root, "results_20261005_100000")
        runner.state = "running"

        class Busy:
            def done(self):
                return False
        runner.task = Busy()
        r = await self.client.delete("/api/runs/results_20261005_100000")
        self.assertEqual(r.status, 409)
        runner.task = None


class Schluessel(AioHTTPTestCase):
    """Desktop-App: Das Backend antwortet nur mit dem Schlüssel, den die App beim Start vergibt."""
    async def get_application(self):
        return sw.make_app(tempfile.mkdtemp(), token="geheimer-schluessel")

    async def test_ohne_schluessel_kein_zugriff(self):
        self.assertEqual((await self.client.get("/api/state")).status, 403)
        self.assertEqual((await self.client.get("/api/state", headers={"X-Last-Token": "falsch"})).status, 403)
        r = await self.client.get("/api/state", headers={"X-Last-Token": "geheimer-schluessel"})
        self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
