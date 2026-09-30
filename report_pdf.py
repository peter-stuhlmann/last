# -*- coding: utf-8 -*-
"""
Einseitiger PDF-Bericht (A4) für den LLM-Härtetest – zum Ausdrucken oder Weiterleiten.

Enthält dasselbe wie die Empfehlungs- und Zusammenfassungsfolien der PowerPoint:
Urteil in einem Satz, die vier wichtigsten Zahlen, Begründung, zwei Diagramme und alle
Ergebnisse als Ampel-Liste. Benötigt reportlab (pip install reportlab).
"""

import math
import os

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from llm_stresstest import capacity, economics, fmt, verdict
from report_pptx import (INFO, INK, INK2, MUTED, REF, S1, S2, STATUS, eur, headline_cards, n0,
                         per_min, result_rows)

PW, PH = A4
M = 34  # Seitenrand (pt)

# Schriften mit ≈, → und € – je nach Betriebssystem die erste vorhandene
_WIN = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
FONT_CANDIDATES = [
    (os.path.join(_WIN, "calibri.ttf"), os.path.join(_WIN, "calibrib.ttf")),
    (os.path.join(_WIN, "arial.ttf"), os.path.join(_WIN, "arialbd.ttf")),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]


def _fonts():
    for reg, bold in FONT_CANDIDATES:
        if os.path.isfile(reg) and os.path.isfile(bold):
            try:
                pdfmetrics.registerFont(TTFont("Body", reg))
                pdfmetrics.registerFont(TTFont("Body-Bold", bold))
                return "Body", "Body-Bold", True
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold", False  # ohne ≈ und →


class Page:
    def __init__(self, path):
        self.c = canvas.Canvas(path, pagesize=A4)
        self.reg, self.bold, self.unicode = _fonts()

    def clean(self, s):
        s = str(s)
        if not self.unicode:
            s = s.replace("≈", "ca.").replace("→", "->").replace("≤", "<=").replace("≥", ">=")
        return s

    def text(self, x, y, s, size=9, bold=False, color=INK, align="left"):
        c = self.c
        c.setFont(self.bold if bold else self.reg, size)
        c.setFillColor(HexColor("#" + color))
        s = self.clean(s)
        {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](x, y, s)

    def para(self, x, y, w, s, size=9, bold=False, color=INK, lead=None, max_lines=None):
        """Umbrechender Text ab Oberkante y; liefert die neue Unterkante."""
        lead = lead or size * 1.25
        lines = simpleSplit(self.clean(s), self.bold if bold else self.reg, size, w)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" .,") + " …"
        for i, ln in enumerate(lines):
            self.text(x, y - size - i * lead, ln, size, bold, color)
        return y - size - (len(lines) - 1) * lead - size * 0.3

    def box(self, x, y, w, h, color, r=6):
        self.c.setFillColor(HexColor("#" + color))
        self.c.roundRect(x, y, w, h, r, stroke=0, fill=1)

    def dot(self, x, y, d, color):
        self.c.setFillColor(HexColor("#" + color))
        self.c.circle(x + d / 2, y + d / 2, d / 2, stroke=0, fill=1)


def _nice(v):
    if v <= 0:
        return 1
    e = 10 ** math.floor(math.log10(v))
    m = v / e
    return (1 if m <= 1 else 2 if m <= 2 else 2.5 if m <= 2.5 else 5 if m <= 5 else 10) * e


def chart(pg, x, y, w, h, title, series, x_label, y_label, ref=None, ref_label=None, dec=0):
    """Kleines Liniendiagramm. series: [(Name, Farbe, [(x, y), …])]; y = Unterkante."""
    c = pg.c
    pg.text(x, y + h - 10, title, 9.5, True)
    L, B, T = 34, 30, (30 if len(series) > 1 else 18)  # Ränder für Achsen, Titel und Legende
    px0, py0, pw, ph = x + L, y + B, w - L - 6, h - B - T
    pts = [p for _, _, ps in series for p in ps if p[1] is not None]
    if not pts:
        pg.text(x + w / 2, y + h / 2, "keine Daten", 8, color=MUTED, align="center")
        return
    xs = [p[0] for p in pts]
    x0, x1 = min(xs), max(xs)
    x1 = x1 if x1 > x0 else x0 + 1
    ymax_raw = max([p[1] for p in pts] + ([ref] if ref else [])) * 1.05
    step = _nice(ymax_raw / 4)
    n = max(1, int(-(-ymax_raw // step)))
    ymax = step * n
    sx = lambda v: px0 + (v - x0) / (x1 - x0) * pw  # noqa: E731
    sy = lambda v: py0 + v / ymax * ph  # noqa: E731
    c.setLineWidth(0.5)
    for k in range(n + 1):
        yy = sy(step * k)
        c.setStrokeColor(HexColor("#E5E7EB"))
        c.line(px0, yy, px0 + pw, yy)
        pg.text(px0 - 4, yy - 2.5, fmt(float(step * k), dec if step < 10 else 0), 6.5, color=MUTED, align="right")
    for k in range(5):
        v = x0 + (x1 - x0) * k / 4
        pg.text(sx(v), py0 - 9, fmt(float(v), 0), 6.5, color=MUTED, align="center")
    pg.text(px0 + pw / 2, py0 - 18, x_label, 7, color=MUTED, align="center")
    c.saveState()
    c.translate(x + 7, py0 + ph / 2)
    c.rotate(90)
    pg.text(0, 0, y_label, 7, color=MUTED, align="center")
    c.restoreState()
    if ref:
        c.setStrokeColor(HexColor("#" + REF))
        c.setDash(3, 2)
        c.line(px0, sy(ref), px0 + pw, sy(ref))
        c.setDash()
        if ref_label:
            pg.text(px0 + pw - 2, sy(ref) + 2.5, ref_label, 6.5, color=MUTED, align="right")
    lx = x
    for name, col, ps in series:
        ps = [p for p in ps if p[1] is not None]
        c.setStrokeColor(HexColor("#" + col))
        c.setFillColor(HexColor("#" + col))
        c.setLineWidth(1.6)
        path = c.beginPath()
        for i, (vx, vy) in enumerate(ps):
            (path.moveTo if i == 0 else path.lineTo)(sx(vx), sy(min(vy, ymax)))
        c.drawPath(path, stroke=1, fill=0)
        for vx, vy in ps:
            c.circle(sx(vx), sy(min(vy, ymax)), 1.8, stroke=0, fill=1)
        if len(series) > 1:  # Legende in einer Zeile unter dem Titel
            pg.box(lx, y + h - 21, 8, 3, col, r=1)
            pg.text(lx + 11, y + h - 22.5, name, 7, color=INK2)
            lx += pdfmetrics.stringWidth(pg.clean(name), pg.reg, 7) + 22


def build_pdf(summary, path):
    pg = Page(path)
    c = pg.c
    cfg, meta = summary.get("config", {}), summary.get("meta", {})
    slo_t = cfg.get("slo_ttft", 2.0)
    vd = verdict(summary)
    cap_ = capacity(summary)
    eco = economics(summary)
    quality = (summary.get("quality") or {}).get("overall", "–")
    cw = PW - 2 * M
    y = PH - M

    # Kopf
    pg.text(M, y - 8, "LLM-HÄRTETEST · KURZBERICHT", 7.5, True, MUTED)
    pg.text(M, y - 30, "Wie belastbar ist unser KI-Server?", 19, True)
    started = (meta.get("started") or "")[:16].replace("T", " ")
    pg.text(M, y - 45, f"{cfg.get('model') or '?'} · getestet am {started} · {cfg.get('base_url', '')}",
            8.5, color=INK2)
    y -= 58

    # Urteil
    pg.box(M, y - 32, cw, 32, STATUS[vd["status"]])
    pg.text(M + 12, y - 21, vd["headline"], 14, True, "FFFFFF")
    y -= 42

    # Die vier Zahlen
    cards = headline_cards(summary)
    gap = 8
    bw = (cw - gap * (len(cards) - 1)) / max(1, len(cards))
    for i, (v, lbl, mean_, col) in enumerate(cards):
        bx = M + i * (bw + gap)
        pg.box(bx, y - 66, bw, 66, "F1F5F9")
        pg.text(bx + 9, y - 25, v, 18, True, col)
        pg.para(bx + 9, y - 30, bw - 18, lbl, 8, True, INK2, max_lines=1)
        pg.para(bx + 9, y - 41, bw - 18, mean_, 7, color=MUTED, max_lines=2)
    y -= 78

    # Warum?
    pg.text(M, y - 10, "Warum?", 10, True, S1)
    y -= 15
    for st, t_ in vd["reasons"][:5]:
        pg.dot(M + 1, y - 9, 6, STATUS[st])
        y = pg.para(M + 13, y, cw - 13, t_, 8.5, max_lines=1) - 2.5
    y -= 6

    # Zwei Diagramme – so hoch, wie der Platz neben der Ergebnisliste erlaubt
    rows = result_rows(summary)
    foot_top = M + 44
    ch_h = max(140, min(230, y - foot_top - 26 - len(rows) * 16 - 18))
    half = (cw - 14) / 2
    rate = sorted((summary.get("rate") or {}).get("stages", []), key=lambda s: s["rate"])
    steps = sorted((summary.get("ramp") or {}).get("steps", []), key=lambda s: s["concurrency"])
    if rate:
        chart(pg, M, y - ch_h, half, ch_h, "Wartezeit, wenn die Fragen zufällig kommen",
              [("normal", S1, [(s["rate"] * 60, s["ttft_p50"]) for s in rate]),
               ("fast alle", S2, [(s["rate"] * 60, s["ttft_p95"]) for s in rate])],
              "Fragen pro Minute", "Sekunden bis zum ersten Wort", slo_t, f"Ziel ≤ {fmt(slo_t, 1)} s", 1)
    else:
        chart(pg, M, y - ch_h, half, ch_h, "Wartezeit bei zunehmendem Andrang",
              [("normal", S1, [(s["concurrency"], s["ttft_p50"]) for s in steps]),
               ("fast alle", S2, [(s["concurrency"], s["ttft_p95"]) for s in steps])],
              "Fragen gleichzeitig", "Sekunden bis zum ersten Wort", slo_t, f"Ziel ≤ {fmt(slo_t, 1)} s", 1)
    chart(pg, M + half + 14, y - ch_h, half, ch_h, "Gesamtleistung",
          [("alle zusammen", S1, [(s["concurrency"], s["out_tps"]) for s in steps])],
          "Fragen gleichzeitig", "Tokens pro Sekunde")
    y -= ch_h + 12

    # Alle Ergebnisse als Ampel-Liste
    pg.text(M, y - 10, "Alle Ergebnisse", 10, True, S1)
    y -= 16
    rh = max(11.5, min(16, (y - foot_top) / max(1, len(rows))))
    rows = rows[:int((y - foot_top) // rh)]
    for i, (col, area, res) in enumerate(rows):
        yy = y - (i + 1) * rh
        if i % 2 == 0:
            c.setFillColor(HexColor("#F8FAFC"))
            c.rect(M, yy, cw, rh, stroke=0, fill=1)
        pg.dot(M + 5, yy + rh / 2 - 3, 6, col or INFO)
        pg.text(M + 17, yy + rh / 2 - 3, area, 8.5, True)
        pg.para(M + 150, yy + rh / 2 + 5.2, cw - 155, res, 8.5, color=INK2, max_lines=1)

    # Fuß: Annahmen
    notes = [f"Aktive Nutzer nach dem Gesetz von Little bei {n0(cap_.get('think_time', 60))} s Pause zwischen "
             f"zwei Fragen einer Person – eine Schätzung, keine Garantie. Verlässlichkeit der Messung: {quality}."]
    if eco:
        notes.append(f"Kosten: Kaufpreis {eur(eco['hw_price'])} über {n0(eco['amort_months'])} Monate, "
                     f"{n0(eco['server_watts'])} W zu {fmt(eco['power_price'], 2)} €/kWh; Cloud "
                     f"{fmt(eco['cloud_price_in'], 2)} € / {fmt(eco['cloud_price_out'], 2)} € je Mio. Tokens "
                     f"rein/raus; {n0(eco['work_hours'])} Arbeitsstunden im Monat. Nicht enthalten: Wartung, "
                     "Einrichtung, Datenschutz-Vorteil.")
    if cap_.get("rate_ok"):
        notes.append(f"Echter Andrang: flüssig bis {per_min(cap_['rate_ok'])} Fragen pro Minute.")
    c.setStrokeColor(HexColor("#E5E7EB"))
    c.line(M, foot_top - 4, M + cw, foot_top - 4)
    yy = foot_top - 8
    for t_ in notes:
        yy = pg.para(M, yy, cw, t_, 6.8, color=MUTED, max_lines=2) - 1
    pg.text(M + cw, M - 12, "Erstellt mit llm_stresstest.py · Details in der PowerPoint", 6.5,
            color=MUTED, align="right")
    c.setTitle("LLM-Härtetest – Kurzbericht")
    c.setAuthor("llm_stresstest.py")
    c.showPage()
    c.save()
    return path

