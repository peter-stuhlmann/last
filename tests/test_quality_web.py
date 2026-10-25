"""Wie sehr kann man den Zahlen des Website-Tests trauen? (Aufpasser für den Messrechner)"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_report_web import sample  # noqa: E402
from test_web_stresstest import Site, make_args  # noqa: E402

import report_web as rw  # noqa: E402
import web_stresstest as ws  # noqa: E402
from report_pptx import BAD, GOOD, WARN  # noqa: E402


def with_lag(*lags, late=None, n_window=40):
    """Beispiel-Lauf, bei dem der Messrechner je Stufe so viele ms hinterherhinkte."""
    s = sample()
    for step, lag in zip(s["ramp"]["steps"], lags):
        step["client_lag_ms"] = lag
        step["n_window"] = n_window
    for stage in s["rate"]["stages"]:
        stage["client_lag_ms"] = 5.0
        stage["send_late_ms"] = late if late is not None else 3.0
    return s


class Verlaesslichkeit(unittest.TestCase):
    def test_sauberer_lauf(self):
        q = ws.assess_quality(with_lag(2, 4, 9, 20))
        self.assertEqual(q["overall"], "hoch")
        self.assertTrue(all(i["status"] == "good" for i in q["items"]))
        self.assertEqual(set(q["items"][0]), {"status", "title", "value", "text", "key", "short"})

    def test_nur_entscheidende_stufen_zaehlen(self):
        # Scheitert schon die Stufe 32, fließt 64 in keine Zahl ein – wie überlastet der Rechner dort war, ist egal
        s = with_lag(2, 4, 9, 400)
        s["ramp"]["steps"][2]["e2e_p95"] = 4.0
        item = next(i for i in ws.assess_quality(s)["items"] if i.get("key") == "lag")
        self.assertEqual(item["status"], "good")

    def test_ueberlasteter_messrechner_wird_benannt(self):
        q = ws.assess_quality(with_lag(2, 4, 40, 400))
        self.assertEqual(q["overall"], "niedrig")
        item = next(i for i in q["items"] if "Messrechner" in i["title"])
        self.assertEqual(item["status"], "bad")
        self.assertIn("64 gleichzeitig", item["value"])
        self.assertIn("400", item["value"])

    def test_knapp_ist_eine_warnung(self):
        q = ws.assess_quality(with_lag(2, 4, 9, 80))
        item = next(i for i in q["items"] if "Messrechner" in i["title"])
        self.assertEqual(item["status"], "warn")
        self.assertEqual(q["overall"], "hoch")          # eine einzelne Warnung kippt das Urteil nicht

    def test_zwei_warnungen_ergeben_mittel(self):
        q = ws.assess_quality(with_lag(2, 4, 9, 80, late=120))
        self.assertEqual(q["overall"], "mittel")

    def test_zu_wenige_messungen(self):
        q = ws.assess_quality(with_lag(2, 4, 9, 20, n_window=6))
        item = next(i for i in q["items"] if "Messungen" in i["title"])
        self.assertEqual(item["status"], "warn")

    def test_ohne_lasttest_keine_aussage(self):
        s = {"config": sample()["config"], "meta": {}}
        self.assertEqual(ws.assess_quality(s), {"overall": "hoch", "items": []})


class Auswirkung(unittest.TestCase):
    def test_ueberlasteter_rechner_kippt_gutes_urteil_nicht(self):
        # Ist nur der Messrechner am Limit, sind die Werte zu schlecht – Grün bleibt Grün, mit Hinweis
        s = with_lag(2, 4, 40, 400)
        s["quality"] = ws.assess_quality(s)
        v = ws.verdict(s)
        self.assertEqual(v["status"], "good")
        self.assertIn(("info", "Dein Rechner war beim Erzeugen der Last am Limit – die Website schafft "
                               "vermutlich sogar mehr als gemessen."), [tuple(r) for r in v["reasons"]])

    def test_verspaetete_besucher_warnen(self):
        # Kamen die Besucher nicht pünktlich, ist die Zahl eher zu gut – das muss gelb werden
        s = with_lag(2, 4, 9, 20, late=400)
        s["quality"] = ws.assess_quality(s)
        v = ws.verdict(s)
        self.assertEqual(v["status"], "warn")
        self.assertTrue(any("eher zu hoch" in text for _, text in v["reasons"]))

    def test_bericht_nennt_die_verlaesslichkeit(self):
        s = with_lag(2, 4, 40, 400)
        s["quality"] = ws.assess_quality(s)
        rows = {area: (color, text) for color, area, text in rw.result_rows(s)}
        self.assertEqual(rows["Verlässlichkeit der Messung"][0], BAD)
        self.assertEqual(rows["Verlässlichkeit der Messung"][1],
                         "niedrig – dein Rechner war am Limit – die Werte sind eher zu schlecht")
        clean = with_lag(2, 4, 9, 20)
        clean["quality"] = ws.assess_quality(clean)
        self.assertEqual({a: c for c, a, _ in rw.result_rows(clean)}["Verlässlichkeit der Messung"], GOOD)
        warn = with_lag(2, 4, 9, 80, late=120)
        warn["quality"] = ws.assess_quality(warn)
        self.assertEqual({a: c for c, a, _ in rw.result_rows(warn)}["Verlässlichkeit der Messung"], WARN)

    def test_powerpoint_erklaert_die_pruefung(self):
        s = with_lag(2, 4, 40, 400)
        s["quality"] = ws.assess_quality(s)
        path = os.path.join(tempfile.mkdtemp(), "b.pptx")
        rw.build_report(s, path)
        from test_report_web import all_text
        text = all_text(path)
        self.assertIn("Kam der Messrechner hinterher?", text)
        self.assertIn("Wie verlässlich ist die Messung?", text)


class EinzelneFehler(unittest.TestCase):
    """Ein paar Verbindungsabbrüche unter Zehntausenden Aufrufen sind Netz-Rauschen, kein Problem."""

    def soak(self, errors, n=35114):
        from test_report_web import page
        s = sample()
        s["soak"]["total"] = page(n=n, ok=n - errors, errors=errors, error_rate=errors / n)
        return s

    def test_vereinzelte_fehler_bleiben_gruen(self):
        s = self.soak(2)
        v = ws.verdict(s)
        self.assertEqual(v["status"], "good")
        self.assertIn("nur 2 der 35.114 Aufrufe gingen schief", " ".join(t for _, t in v["reasons"]))
        rows = {area: (color, text) for color, area, text in rw.result_rows(s)}
        self.assertEqual(rows["Ausdauer"][0], GOOD)
        self.assertIn("nur 2 der 35.114 schiefgegangen", rows["Ausdauer"][1])

    def test_spuerbare_fehler_werden_gelb_dann_rot(self):
        self.assertEqual(ws.verdict(self.soak(100))["status"], "warn")        # 0,3 %
        v = ws.verdict(self.soak(1000))                                         # 2,8 %
        self.assertEqual(v["status"], "bad")
        self.assertIn("gingen 1.000 der 35.114 Aufrufe schief (2,8 %)", " ".join(t for _, t in v["reasons"]))
        self.assertEqual({a: c for c, a, _ in rw.result_rows(self.soak(1000))}["Ausdauer"], BAD)

    def test_ein_fehler_kostet_keine_stufe(self):
        cfg = sample()["config"]
        from test_report_web import step
        self.assertTrue(ws.meets_slo(step(32, n=2000, errors=1, error_rate=1 / 2000), cfg))
        self.assertFalse(ws.meets_slo(step(32, n=500, errors=1, error_rate=1 / 500), cfg))


class Aufpasser(unittest.IsolatedAsyncioTestCase):
    async def test_misst_verzug_der_eigenen_schleife(self):
        st = ws.WebStressTest(make_args("http://127.0.0.1:9/"), tempfile.mkdtemp())
        import asyncio
        task = asyncio.create_task(st.lag_watch())
        t0 = time.perf_counter()
        await asyncio.sleep(0.25)
        time.sleep(0.5)                       # blockiert die Schleife: der Wecker klingelt zu spät
        await asyncio.sleep(0.25)
        task.cancel()
        st.raw.close()
        self.assertGreater(st.lag_ms(t0, time.perf_counter()), 150)
        self.assertIsNone(st.lag_ms(t0 - 100, t0 - 50))

    async def test_lauf_enthaelt_die_pruefung(self):
        site = Site()
        url = await site.start()
        try:
            st = ws.WebStressTest(make_args(url, cooldown=0, spike_idle=0), tempfile.mkdtemp())
            await st.run()
        finally:
            await site.runner.cleanup()
        s = st.summary
        self.assertIn(s["quality"]["overall"], ("hoch", "mittel", "niedrig"))
        self.assertTrue(all("client_lag_ms" in x for x in s["ramp"]["steps"]))
        self.assertTrue(all("client_lag_ms" in x and "send_late_ms" in x for x in s["rate"]["stages"]))
        self.assertTrue(any("Messrechner" in i["title"] for i in s["quality"]["items"]))


if __name__ == "__main__":
    unittest.main()
