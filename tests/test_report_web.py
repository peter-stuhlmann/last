"""Tests für die Berichte zum Website-Lasttest (PowerPoint, PDF, Vergleich)."""
import asyncio
import os
import sys
import tempfile
import unittest

from pptx import Presentation

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_web_stresstest import Site, make_args  # noqa: E402

import report_web as rw  # noqa: E402
import stresstest_web as sw  # noqa: E402
from report_pptx import BAD, GOOD, WARN  # noqa: E402


def page(**over):
    s = {"n": 40, "ok": 40, "errors": 0, "error_rate": 0.0, "error_types": {}, "wall_s": 30.0,
         "ttft_p50": 0.08, "ttft_p95": 0.12, "ttft_max": 0.2, "e2e_p50": 0.6, "e2e_p95": 0.9,
         "e2e_mean": 0.65, "e2e_max": 1.2, "req_s": 10.0, "bytes_s": 5e5, "bytes_avg": 480000,
         "files_avg": 13, "out_tps": None, "user_tps_p50": None}
    s.update(over)
    return s


def step(c, **over):
    return {**page(**over), "concurrency": c, "fine": False, "goodput_pct": 100.0, "n_window": 40,
            "window_s": 30.0}


def sample(**over):
    """Ein vollständiger Website-Lauf mit „Grünes Licht“."""
    s = {
        "config": {"kind": "web", "base_url": "https://shop.example/", "tests": "baseline,ramp,rate,spike,soak",
                   "levels": "1,16,32,64", "level_seconds": 30, "think_time": 30.0, "target_users": 500,
                   "slo_load": 3.0, "spike_size": 32, "soak_minutes": 3.0, "include_assets": True},
        "meta": {"started": "2026-10-05T10:00:00", "finished": "2026-10-05T10:12:00", "host": "messrechner",
                 "current_test": None},
        "prechecks": {"status": 200, "bytes": 48000, "assets": 12, "total_bytes": 480000,
                      "final_url": "https://shop.example/", "rtt_ms": 80.0, "busy": None,
                      "files": [{"path": "/bilder/titel.jpg", "bytes": 310000, "ms": 120.0},
                                {"path": "/app.js", "bytes": 90000, "ms": 60.0}]},
        "baseline": page(),
        "ramp": {"steps": [step(1, req_s=1.5, e2e_p95=0.7), step(16, req_s=20.0, e2e_p95=1.1),
                           step(32, req_s=31.0, e2e_p95=2.4, ttft_p95=0.9),
                           step(64, req_s=34.0, e2e_p95=6.5, ttft_p95=3.1, goodput_pct=40.0)],
                 "break": None, "saturated": None},
        "rate": {"stages": [{**page(), "rate": 12.5, "rate_actual": 12.5, "overloaded": False,
                             "max_inflight": 9},
                            {**page(e2e_p95=1.4), "rate": 25.0, "rate_actual": 25.0, "overloaded": False,
                             "max_inflight": 22}],
                 "break": None, "think_time": 30.0},
        "spike": {"size": 32, "burst": page(e2e_max=4.2), "recovery": page(), "recovered": True,
                  "crashed": False},
        "soak": {"minutes": 3.0, "concurrency": 32, "total": page(),
                 "buckets": [{"t_min": 1.0, "s": page()}, {"t_min": 2.0, "s": page(e2e_p50=0.62)},
                             {"t_min": 3.0, "s": page(e2e_p50=0.63)}],
                 "degradation": {"tps_change_pct": 1.0, "ttft_change_pct": 4.0}},
        "control": {"s": page(), "tps_diff_pct": -3.0, "ttft_diff_pct": 3.0},
        "probes": None, "economics": None,
    }
    s.update(over)
    return s


def all_text(path):
    out = []
    for slide in Presentation(path).slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                out.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    out.extend(cell.text for cell in row.cells)
    return "\n".join(out)


class Kernaussagen(unittest.TestCase):
    def test_vier_zahlen_fuer_die_entscheidung(self):
        cards = rw.headline_cards(sample())
        self.assertEqual(len(cards), 4)
        self.assertEqual(cards[0][0], "≈ 770")                 # 25 Aufrufe/s × (0,65 s + 30 s)
        self.assertEqual(cards[0][1], "Besucher gleichzeitig")
        self.assertIn("500", cards[0][2])
        self.assertEqual(cards[0][3], GOOD)
        self.assertEqual(cards[1][0], "0,60 s")
        self.assertEqual(cards[2][0], "32")
        self.assertEqual(cards[3][0], "2.040")                 # 34 Seiten/s × 60

    def test_zu_wenig_kapazitaet_wird_rot(self):
        s = sample()
        s["config"]["target_users"] = 5000
        self.assertEqual(rw.headline_cards(s)[0][3], BAD)

    def test_ampelzeilen(self):
        rows = {area: (color, text) for color, area, text in rw.result_rows(sample())}
        self.assertEqual(rows["Ladezeit ohne Andrang"][0], GOOD)
        self.assertIn("bis 32 Besucher", rows["Gleichzeitig flüssig"][1])
        self.assertIn("1.500 Aufrufe/min", rows["Echter Andrang"][1])
        self.assertEqual(rows["Großer Ansturm"][0], GOOD)
        self.assertEqual(rows["Ausdauer"][0], GOOD)
        self.assertIn("Gewicht der Seite", rows)

    def test_probleme_werden_benannt(self):
        s = sample()
        s["ramp"]["break"] = {"concurrency": 64, "reason": "zu viele Fehler: 12 %"}
        s["spike"]["crashed"] = True
        s["soak"]["degradation"]["ttft_change_pct"] = 60.0
        rows = {area: (color, text) for color, area, text in rw.result_rows(s)}
        self.assertEqual(rows["Belastungsgrenze"][0], BAD)
        self.assertIn("ab 64", rows["Belastungsgrenze"][1])
        self.assertEqual(rows["Großer Ansturm"][0], BAD)
        self.assertEqual(rows["Ausdauer"][0], WARN)


class PowerPoint(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "bericht.pptx")

    def test_vollstaendiger_bericht(self):
        rw.build_report(sample(), self.path)
        prs = Presentation(self.path)
        self.assertGreaterEqual(len(prs.slides), 11)
        text = all_text(self.path)
        for expected in ("Wie viele Besucher hält unsere Website aus?", "https://shop.example/",
                         "Die Website hält dem Andrang stand.", "Besucher gleichzeitig",
                         "Unsere Empfehlung", "Echter Andrang", "Großer Ansturm", "Ausdauer",
                         "/bilder/titel.jpg", "Alles auf einen Blick"):
            self.assertIn(expected, text)
        # Nichts aus dem KI-Bericht und keine rohen Platzhalter
        for forbidden in ("Token", "tok/s", "KI-Server"):
            self.assertNotIn(forbidden, text)
        self.assertNotRegex(text, r"(None|nan)")
        # Jede Folie hat Sprechernotizen (dort stehen die Fachbegriffe)
        self.assertTrue(all(sl.has_notes_slide and sl.notes_slide.notes_text_frame.text for sl in prs.slides))

    def test_abgebrochener_lauf_ergibt_trotzdem_einen_bericht(self):
        s = sample()
        for key in ("rate", "spike", "soak", "control"):
            del s[key]
        s["prechecks"].pop("files")
        rw.build_report(s, self.path)
        text = all_text(self.path)
        self.assertIn("Unsere Empfehlung", text)
        self.assertNotIn("Großer Ansturm", text)
        self.assertNotRegex(text, r"(None|nan)")

    def test_nur_vorab_check(self):
        s = {"config": sample()["config"], "meta": {}, "prechecks": sample()["prechecks"]}
        rw.build_report(s, self.path)
        self.assertIn("Für ein Urteil fehlen die Lasttests.", all_text(self.path))


class Pdf(unittest.TestCase):
    def test_eine_seite(self):
        path = os.path.join(tempfile.mkdtemp(), "bericht.pdf")
        self.assertEqual(rw.build_pdf(sample(), path), path)
        with open(path, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(data.count(b"/Type /Page\n") + data.count(b"/Type /Page "), 1)

    def test_unvollstaendige_daten(self):
        path = os.path.join(tempfile.mkdtemp(), "bericht.pdf")
        s = sample()
        del s["rate"], s["spike"], s["soak"], s["control"]
        rw.build_pdf(s, path)
        self.assertGreater(os.path.getsize(path), 3000)


class Vergleich(unittest.TestCase):
    def test_zwei_laeufe(self):
        before = sample()
        after = sample()
        after["meta"]["started"] = "2026-10-06T09:00:00"
        after["baseline"] = page(e2e_p50=0.3)
        for st in after["ramp"]["steps"]:
            st["e2e_p95"] = st["e2e_p95"] / 2
            st["req_s"] = st["req_s"] * 1.5
        path = os.path.join(tempfile.mkdtemp(), "vergleich.pptx")
        rw.build_compare([before, after], path, ["vorher", "nachher"])
        text = all_text(path)
        for expected in ("vorher", "nachher", "Ladezeit ohne Andrang", "0,60 s", "0,30 s", "−50 %"):
            self.assertIn(expected, text)
        self.assertNotIn("Token", text)
        self.assertGreaterEqual(len(Presentation(path).slides), 4)

    def test_art_der_laeufe_muss_zusammenpassen(self):
        self.assertIs(sw.comparison_builder(["web", "web"]), rw.build_comparison)
        self.assertIs(sw.comparison_builder(["llm", "llm"]), sw.lt.build_comparison)
        with self.assertRaisesRegex(ValueError, "gleicher Art"):
            sw.comparison_builder(["web", "llm"])


class NachDemLauf(unittest.IsolatedAsyncioTestCase):
    async def test_runner_erstellt_powerpoint_und_pdf(self):
        site = Site()
        url = await site.start()
        root = tempfile.mkdtemp()
        runner = sw.Runner(root)
        try:
            name = runner.start(make_args(url, cooldown=0, spike_idle=0, tests="baseline,ramp"))
            await asyncio.wait_for(runner.task, 60)
        finally:
            await site.runner.cleanup()
        self.assertEqual(runner.state, "done", runner.error)
        self.assertTrue(os.path.isfile(os.path.join(root, name, sw.REPORT_NAME)))
        self.assertTrue(os.path.isfile(os.path.join(root, name, sw.PDF_NAME)))
        self.assertTrue(runner.report and runner.pdf)
        # Die Liste der größten Dateien und der Zeitverlauf der Ausdauer kommen aus dem echten Lauf
        files = runner.st.summary["prechecks"]["files"]
        self.assertEqual(len(files), 3)
        self.assertEqual(set(files[0]), {"path", "bytes", "ms"})
        self.assertEqual(runner.st.summary["prechecks"]["total_bytes"], len(files) * 1000 + runner.st.summary["prechecks"]["bytes"])


if __name__ == "__main__":
    unittest.main()
