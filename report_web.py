# -*- coding: utf-8 -*-
"""
Berichte für den Website-Lasttest – in einfacher Sprache.

  build_report      PowerPoint mit allen Ergebnissen
  build_pdf         Kurzbericht auf einer A4-Seite
  build_compare     Vergleich zweier oder mehrerer Läufe (z. B. vorher / nachher)

Durchgehendes Bild: Die Website ist ein Laden. Jeder Besucher kommt herein, schaut sich das
Schaufenster an (die Seite) und wartet, bis alles ausgepackt ist (Bilder, Styles, Skripte).
Fachbegriffe stehen in den Notizen der Folien.

Gestaltung und Bausteine kommen aus report_pptx.py und report_pdf.py, damit beide Berichte
gleich aussehen.
"""

import datetime as dt
import json
import os

from pptx.enum.text import MSO_ANCHOR

from llm_stresstest import IN_DOCKER, fmt, round_users
from report_pptx import (BAD, CARD, DARK_BG, GOOD, INFO, INK, INK2, MUTED, PANEL, S1, S2, S3, S4,
                         STATUS, W, WARN, Deck, bar_chart, dot, explain, footer, line_chart, mins,
                         n0, notes, per_min, rect, secs, stat, table, text, time_feel, title)
from web_stresstest import DEFAULTS, capacity, meets_slo, verdict

GOOD_TTFB, SLOW_TTFB = 0.5, 1.5            # Richtwerte für die erste Antwort des Servers (s)
LIGHT_PAGE, HEAVY_PAGE = 2e6, 5e6          # Richtwerte für das Gewicht einer Seite (Bytes)


# ════════════════════════════════════════════════════════════════════════════
#  Gemeinsame Aussagen (PowerPoint und PDF sagen dasselbe)
# ════════════════════════════════════════════════════════════════════════════

def size(b):
    """Dateigröße lesbar: 480 kB, 1,2 MB."""
    if b is None:
        return "–"
    return fmt(b / 1e6, 1, " MB") if b >= 1e6 else fmt(b / 1e3, 0, " kB")


def approx(v):
    return "–" if v is None else n0(round_users(v))


def when(summary):
    """Startzeit des Laufs als 05.10.2026, 10:00 (leer, wenn unbekannt)."""
    iso = ((summary.get("meta") or {}).get("started") or "")[:16]
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d.%m.%Y, %H:%M")
    except ValueError:
        return ""


def host_line(summary):
    """Name des Messrechners – im Docker-Container ist das nur eine zufällige Kennung, also weglassen."""
    host = (summary.get("meta") or {}).get("host")
    return f"Messrechner: {host}" if host and not IN_DOCKER else ""


def control_note(summary):
    """Kontrollmessung in Worten. Unterschiede unter 5 % oder 0,05 s sind Messrauschen."""
    ctl, base = summary.get("control") or {}, summary.get("baseline") or {}
    d = ctl.get("ttft_diff_pct")
    if d is None:
        return None
    a, b = base.get("e2e_p50"), (ctl.get("s") or {}).get("e2e_p50")
    same = abs(d) < 5 or (a is not None and b is not None and abs(b - a) < 0.05)
    return (GOOD, "so schnell wie am Anfang") if same else (
        GOOD if d <= 25 else WARN, f"{signed(d)} Ladezeit gegenüber dem Anfang")


def signed(p):
    """+12 %, −50 %, ±0 % – mit echtem Minuszeichen."""
    if p is None:
        return "–"
    r = round(p)
    return f"{'+' if r > 0 else '−' if r < 0 else '±'}{abs(r)} %"


def facts(summary):
    """Alles, was mehrere Folien brauchen, an einer Stelle ausgerechnet."""
    cfg = summary.get("config") or {}
    steps = sorted((summary.get("ramp") or {}).get("steps", []), key=lambda s: s["concurrency"])
    good = [s for s in steps if meets_slo(s, cfg)]
    top = max(steps, key=lambda s: s.get("req_s") or 0) if steps else None
    cap_ = capacity(summary)
    return {
        "cfg": cfg, "slo": cfg.get("slo_load", DEFAULTS["slo_load"]),
        "think": cap_.get("think_time", DEFAULTS["think_time"]),
        "target": cfg.get("target_users") or 0,
        "base": summary.get("baseline"), "pre": summary.get("prechecks") or {},
        "steps": steps, "rec": good[-1] if good else None, "top": top,
        "brk": (summary.get("ramp") or {}).get("break"),
        "stages": sorted((summary.get("rate") or {}).get("stages", []), key=lambda s: s["rate"]),
        "rbrk": (summary.get("rate") or {}).get("break"),
        "spike": summary.get("spike"), "soak": summary.get("soak"), "ctl": summary.get("control"),
        "cap": cap_, "users": cap_.get("users"), "verdict": verdict(summary),
    }


def headline_cards(summary):
    """Die vier Zahlen für die Entscheidung: (Wert, Beschriftung, Erläuterung, Farbe)."""
    f = facts(summary)
    users, target, base, rec, top = f["users"], f["target"], f["base"], f["rec"], f["top"]
    cards = []
    if f["steps"] or f["stages"]:  # ohne Lasttest gibt es keine Besucherzahl
        cards.append((f"≈ {approx(users)}" if users else "0", "Besucher gleichzeitig",
                      f"erwartet: {n0(target)}" if target else f"bei {n0(f['think'])} s Pause zwischen zwei Klicks",
                      (GOOD if not target or users >= target else WARN if users >= 0.7 * target else BAD)
                      if users else BAD))
    if base:
        load = base.get("e2e_p50")
        cards.append((secs(load), "Ladezeit ohne Andrang", time_feel(load),
                      GOOD if load is not None and load <= f["slo"] else WARN))
    if f["steps"]:
        cards.append((str(rec["concurrency"]) if rec else "0", "gleichzeitig ohne Frust",
                      f"fast alle haben die Seite dann nach höchstens {secs(f['slo'])}" if rec
                      else "schon die kleinste Stufe ist zu langsam",
                      GOOD if rec else BAD))
    if top and top.get("req_s"):
        cards.append((n0(top["req_s"] * 60), "Aufrufe pro Minute",
                      "mehr Seiten liefert der Server insgesamt nicht aus", INK))
    return cards


def result_rows(summary):
    """Alle Ergebnisse als Ampel-Zeilen: (Farbe, Bereich, Ergebnis)."""
    f = facts(summary)
    slo, base, steps, rec = f["slo"], f["base"], f["steps"], f["rec"]
    rows = []
    if base:
        load, first = base.get("e2e_p50"), base.get("ttft_p50")
        rows.append((GOOD if load is not None and load <= slo else WARN, "Ladezeit ohne Andrang",
                     f"{secs(load)} bis die Seite komplett da ist – {time_feel(load)}"))
        rows.append((INFO if first is None else GOOD if first <= GOOD_TTFB else WARN if first <= SLOW_TTFB else BAD,
                     "Erste Antwort des Servers",
                     f"{secs(first)} – " + ("zügig" if first is not None and first <= GOOD_TTFB else
                                           "der Server lässt sich Zeit, bevor überhaupt etwas kommt")))
    if steps:
        rows.append((GOOD if rec else BAD, "Gleichzeitig flüssig",
                     f"bis {rec['concurrency']} Besucher laden gleichzeitig, ohne dass es zäh wird" if rec
                     else "schon bei der kleinsten Stufe lädt die Seite zu langsam"))
        if f["brk"]:
            rows.append((BAD, "Belastungsgrenze", f"ab {f['brk']['concurrency']} gleichzeitig: {f['brk']['reason']}"))
        else:
            rows.append((GOOD, "Belastungsgrenze",
                         f"bis {steps[-1]['concurrency']} gleichzeitig keine Fehler und kein Abbruch"))
    if f["stages"]:
        ok = f["cap"].get("rate_ok")
        rows.append((GOOD if ok else BAD, "Echter Andrang",
                     (f"bis {per_min(ok)} Aufrufe/min flüssig" if ok else "schon die kleinste Menge ist zu viel")
                     + (f", ab {per_min(f['rbrk']['rate'])}/min wächst die Schlange" if f["rbrk"] else "")))
    spike = f["spike"]
    if spike:
        burst = spike["burst"]
        if spike.get("crashed"):
            rows.append((BAD, "Großer Ansturm", f"{spike['size']} auf einmal – danach war die Website nicht mehr erreichbar"))
        elif burst["errors"]:
            rows.append((WARN, "Großer Ansturm", f"{spike['size']} auf einmal – {burst['errors']} bekamen eine Fehlerseite"))
        elif spike.get("recovered") is False:
            rows.append((WARN, "Großer Ansturm", f"{spike['size']} auf einmal – alle bedient, danach aber langsamer als vorher"))
        else:
            rows.append((GOOD, "Großer Ansturm",
                         f"{spike['size']} auf einmal – alle bedient, längste Ladezeit {secs(burst.get('e2e_max'))}"))
    soak = f["soak"]
    if soak:
        slower = (soak.get("degradation") or {}).get("ttft_change_pct")
        failed = soak["total"]["error_rate"] > 0
        rows.append((BAD if failed else WARN if slower is not None and slower > 25 else GOOD, "Ausdauer",
                     f"nach {mins(soak['minutes'])} "
                     + (f"{fmt(soak['total']['error_rate'] * 100, 1)} % Fehler" if failed
                        else "unverändert schnell" if slower is None or abs(slower) < 5
                        else f"{signed(slower)} Ladezeit")))
    ctl_note = control_note(summary)
    if ctl_note:
        rows.append((ctl_note[0], "Kontrollmessung am Ende", ctl_note[1]))
    quality = summary.get("quality") or {}
    if quality.get("items"):
        # Der wichtigste Befund zuerst: rot vor gelb vor grün
        worst = min(quality["items"], key=lambda i: ("bad", "warn", "good").index(i["status"]))
        rows.append(({"hoch": GOOD, "mittel": WARN, "niedrig": BAD}[quality["overall"]],
                     "Verlässlichkeit der Messung",
                     f"{quality['overall']} – " + ("der Messrechner kam gut hinterher" if worst["status"] == "good"
                                                   else f"{worst['title']} {worst['value']}")))
    total = f["pre"].get("total_bytes")
    if total:
        rows.append((GOOD if total <= LIGHT_PAGE else WARN if total <= HEAVY_PAGE else BAD, "Gewicht der Seite",
                     f"{size(total)} mit {n0(f['pre'].get('assets', 0))} Dateien"
                     + ("" if total <= LIGHT_PAGE else " – schwer; das kostet bei jedem Besuch Zeit")))
    return rows


def pointers(summary):
    """Mögliche Ansatzpunkte – abgeleitet aus dem, was gemessen wurde. Der Test zeigt,
    wo es hakt, nicht warum; deshalb vorsichtig formuliert."""
    f = facts(summary)
    base, pre, rec, steps = f["base"], f["pre"], f["rec"], f["steps"]
    out = []
    if base and base.get("ttft_p50") is not None and base["ttft_p50"] > GOOD_TTFB:
        out.append(("Der Server braucht schon ohne Andrang lange für die erste Antwort",
                    f"{secs(base['ttft_p50'])}, bevor überhaupt etwas kommt. Oft hilft es, fertige Seiten "
                    "zwischenzuspeichern (Seiten-Cache), statt sie für jeden Besucher neu zu bauen."))
    if pre.get("total_bytes") and pre["total_bytes"] > LIGHT_PAGE:
        biggest = (pre.get("files") or [{}])[0]
        out.append(("Die Seite ist schwer",
                    f"{size(pre['total_bytes'])} pro Besuch"
                    + (f"; allein {biggest['path']} wiegt {size(biggest['bytes'])}" if biggest.get("path") else "")
                    + ". Kleinere Bilder und weniger Skripte entlasten Server und Besucher zugleich."))
    if steps and not rec:
        out.append(("Schon wenige Besucher sind zu viel",
                    "Bevor mehr Leistung gekauft wird, zuerst die Ladezeit ohne Andrang senken – "
                    "sie ist die Untergrenze für alles Weitere."))
    elif rec and steps and rec is not steps[-1]:
        nxt = steps[steps.index(rec) + 1]
        out.append((f"Zwischen {rec['concurrency']} und {nxt['concurrency']} gleichzeitig wird es eng",
                    "Vor Aktionen, Newslettern oder Fernsehauftritten einplanen: mehr Serverleistung, ein "
                    "vorgeschaltetes Auslieferungsnetz (CDN) oder ein Seiten-Cache."))
    if f["target"] and f["users"] and f["users"] < f["target"]:
        out.append(("Die erwartete Besucherzahl wird nicht erreicht",
                    f"Es reicht für ≈ {approx(f['users'])}, erwartet werden {n0(f['target'])}. "
                    "Die Lücke lässt sich nur mit schnellerer Seite oder mehr Leistung schließen."))
    if f["spike"] and (f["spike"].get("crashed") or f["spike"]["burst"]["errors"]):
        out.append(("Ein plötzlicher Ansturm führt zu Fehlern",
                    "Prüfen, ob der Server Anfragen in eine Warteschlange stellen kann, statt sie abzuweisen."))
    if not out:
        out.append(("Kein dringender Handlungsbedarf",
                    "Die Website erreicht alle gesetzten Ziele. Sinnvoll ist, den Test nach größeren "
                    "Änderungen zu wiederholen und die Läufe zu vergleichen."))
    out = out[:3]
    out.append(("Nach jeder Änderung erneut messen",
                "Derselbe Test nach einem Umbau zeigt, ob er geholfen hat. In der Oberfläche lassen sich zwei "
                "Läufe ankreuzen und als Vorher-nachher-Bericht vergleichen."))
    return out


# ════════════════════════════════════════════════════════════════════════════
#  PowerPoint
# ════════════════════════════════════════════════════════════════════════════

def _short(path, n=44):
    return path if len(path) <= n else "…" + path[-(n - 1):]


def _bullets(sl, x, y, w, items, gap=0.95):
    """Nummerierte Kästen untereinander: [(Überschrift, Text)]."""
    for i, (head, body) in enumerate(items):
        yy = y + i * gap
        dot(sl, x, yy + 0.04, 0.42, S1, i + 1, size=14)
        text(sl, x + 0.62, yy, w - 0.62, 0.32, head, size=15, bold=True)
        text(sl, x + 0.62, yy + 0.33, w - 0.62, gap - 0.38, body, size=12.5, color=INK2)


def build_report(summary, path):
    d = Deck()
    f = facts(summary)
    cfg, slo, think = f["cfg"], f["slo"], f["think"]
    base, pre, steps, rec, top = f["base"], f["pre"], f["steps"], f["rec"], f["top"]
    stages, spike, soak, ctl, users, vd = f["stages"], f["spike"], f["soak"], f["ctl"], f["users"], f["verdict"]
    url = cfg.get("base_url", "")
    n_files = pre.get("assets", 0)

    # ═══ Titel ═══
    sl = d.slide(dark=True)
    text(sl, 0.8, 1.55, 11.5, 0.45, "BELASTUNGSTEST", size=15, color="94A3B8", bold=True)
    text(sl, 0.8, 2.0, 11.8, 1.0, "Wie viele Besucher hält unsere Website aus?", size=40, color="FFFFFF",
         bold=True, font="Cambria")
    text(sl, 0.8, 3.05, 11.8, 0.6, url, size=24, color="CBD5E1")
    started = when(summary)
    text(sl, 0.8, 4.4, 11.5, 1.2, [x for x in (f"Getestet am {started}" if started else "Testbericht",
                                               host_line(summary)) if x], size=15, color="94A3B8")
    for i, c in enumerate((S1, S2, S3)):
        dot(sl, 0.8 + i * 0.35, 6.3, 0.2, c)
    notes(sl, "Automatisch erzeugt von web_stresstest.py. Rohdaten: summary.json und raw_requests.jsonl "
              "im Ergebnisordner.")

    # ═══ Empfehlung ═══
    sl = d.slide()
    title(sl, "Unsere Empfehlung")
    rect(sl, 0.6, 1.3, W - 1.2, 1.1, STATUS[vd["status"]])
    text(sl, 1.0, 1.3, W - 2.0, 1.1, vd["headline"], size=28, bold=True, color="FFFFFF",
         anchor=MSO_ANCHOR.MIDDLE, font="Cambria")
    cards = headline_cards(summary)
    if cards:
        cw = (W - 1.2 - 0.25 * (len(cards) - 1)) / len(cards)
        for i, (v, lbl, m, col) in enumerate(cards):
            stat(sl, 0.6 + i * (cw + 0.25), 2.65, cw, 1.95, v, lbl, m, color=col, vsize=30)
    if vd["reasons"]:
        text(sl, 0.6, 4.85, 6, 0.35, "Warum?", size=15, bold=True, color=S1)
        for i, (st_, t_) in enumerate(vd["reasons"][:5]):
            dot(sl, 0.65, 5.32 + i * 0.36, 0.18, STATUS[st_])
            text(sl, 0.98, 5.25 + i * 0.36, W - 1.6, 0.34, t_, size=13, color=INK)
    footer(sl, f"Besucherzahl nach dem Gesetz von Little bei {n0(think)} s Pause zwischen zwei Klicks – "
               "eine Schätzung, keine Garantie.")
    notes(sl, "Urteil: grün, wenn die Kapazität zum erwarteten Andrang passt und Ansturm sowie Dauerlast "
              "sauber überstanden wurden; gelb bei knapper Kapazität, Fehlern im Ansturm oder langsamer "
              "werdender Seite; rot, wenn die Kapazität deutlich nicht reicht oder die Website ausfiel. "
              f"Ziel (SLO): Ladezeit p95 ≤ {fmt(slo, 1)} s, keine Fehler.")

    # ═══ So haben wir getestet ═══
    sl = d.slide()
    title(sl, "So haben wir getestet", "Jeder simulierte Besucher tut, was ein Browser beim ersten Besuch tut")
    _bullets(sl, 0.6, 1.85, 6.4, [
        ("Seite aufrufen", "Der Besucher fragt die Adresse an. Die Zeit, bis der Server die ersten Daten "
                           "schickt, heißt „erste Antwort“."),
        ("Alles nachladen", (f"Danach holt er die {n0(n_files)} Dateien, die zur Seite gehören – Bilder, Styles "
                             "und Skripte derselben Website." if n_files else
                             "In diesem Lauf wurde nur die Seite selbst geholt, ohne zugehörige Dateien.")),
        ("Fertig", "Erst wenn alles da ist, zählt die Seite als geladen. Diese „Ladezeit“ ist das, was "
                   f"Besucher spüren. Ziel: höchstens {secs(slo)}."),
        ("Immer mehr Besucher", "Erst einer allein, dann stufenweise mehr gleichzeitig, dann zufällig "
                                "eintreffend wie im Alltag, ein plötzlicher Ansturm und zum Schluss Dauerlast."),
    ])
    files = pre.get("files") or []
    if files:
        text(sl, 7.5, 1.85, 5.2, 0.35, "Die größten Dateien der Seite", size=14, bold=True, color=S1)
        table(sl, 7.5, 2.3, 5.25, [["Datei", "Größe", "allein geladen in"]]
              + [[_short(x["path"], 34), size(x["bytes"]), fmt(x["ms"], 0, " ms")] for x in files[:7]],
              col_w=[3.0, 0.95, 1.3], font=10.5)
        text(sl, 7.5, 2.4 + 0.34 * (min(len(files), 7) + 1), 5.25, 0.6,
             f"Zusammen wiegt ein Besuch {size(pre.get('total_bytes'))}.", size=12.5, color=INK2)
    else:
        rect(sl, 7.5, 1.85, 5.25, 1.5, PANEL)
        text(sl, 7.8, 2.1, 4.65, 1.0, f"Die Seite selbst ist {size(pre.get('bytes'))} groß.", size=14, color=INK2)
    footer(sl, "Wie beim ersten Besuch: ohne Browser-Cache, jeder Besucher mit eigenen Verbindungen. "
               "Wer wiederkommt, hat es eher leichter.")
    notes(sl, "HTTP GET auf die Adresse, danach parallel (höchstens 6 Verbindungen pro Besucher) alle im HTML "
              "verlinkten Dateien desselben Hosts: link[rel=stylesheet|icon|preload|modulepreload], script[src], "
              "img[src]. Fremde Hosts werden nie angefragt. Erste Antwort = TTFB, Ladezeit = bis zum letzten Byte "
              "der letzten Datei. Kein JavaScript, kein Rendern.")

    # ═══ Einer allein ═══
    if base:
        sl = d.slide()
        title(sl, "Einer allein", "So schnell ist die Seite, wenn sonst niemand da ist")
        first, load = base.get("ttft_p50"), base.get("e2e_p50")
        bw = (W - 1.2 - 0.5) / 3
        stat(sl, 0.6, 1.9, bw, 2.2, secs(first), "Erste Antwort des Servers",
             "so lange braucht der Server, bevor überhaupt etwas kommt",
             color=GOOD if first is not None and first <= GOOD_TTFB else WARN if first is not None and first <= SLOW_TTFB else BAD,
             vsize=36)
        stat(sl, 0.6 + bw + 0.25, 1.9, bw, 2.2, secs(load), "Ladezeit der ganzen Seite", time_feel(load),
             color=GOOD if load is not None and load <= slo else WARN, vsize=36)
        stat(sl, 0.6 + 2 * (bw + 0.25), 1.9, bw, 2.2, size(pre.get("total_bytes") or pre.get("bytes")),
             "Gewicht eines Besuchs", f"die Seite und {n0(n_files)} Dateien", vsize=36)
        rect(sl, 0.6, 4.45, W - 1.2, 2.2, PANEL)
        text(sl, 0.9, 4.65, W - 1.8, 0.35, "Was das bedeutet", size=14, bold=True, color=S1)
        text(sl, 0.9, 5.05, W - 1.8, 1.5, [
            "Schneller als hier wird die Seite unter Last nie – das ist der beste Fall.",
            f"Richtwerte: Eine erste Antwort unter {fmt(GOOD_TTFB, 1)} s gilt als zügig, über {fmt(SLOW_TTFB, 1)} s als träge. "
            f"Bei der Ladezeit haben wir uns höchstens {secs(slo)} vorgenommen.",
            (f"Gemessen: Die Hälfte der Aufrufe war nach {secs(load)} fertig, fast alle (95 %) nach "
             f"{secs(base.get('e2e_p95'))}."),
        ], size=13, color=INK, space_after=6)
        notes(sl, f"Baseline: {base['n']} Aufrufe nacheinander. TTFB p50 {fmt(first, 3)} s / p95 "
                  f"{fmt(base.get('ttft_p95'), 3)} s; Ladezeit p50 {fmt(load, 3)} s / p95 "
                  f"{fmt(base.get('e2e_p95'), 3)} s; Fehler {base['errors']}.")

    # ═══ Immer mehr gleichzeitig ═══
    if steps:
        cats = [s["concurrency"] for s in steps]
        sl = d.slide()
        title(sl, "Immer mehr gleichzeitig", "Ab wann wird die Seite zäh?")
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, cats,
                   [("normal (die Hälfte ist schneller)", [s.get("e2e_p50") for s in steps]),
                    ("fast alle (95 % sind schneller)", [s.get("e2e_p95") for s in steps]),
                    (f"Ziel: {secs(slo)}", [slo] * len(steps))],
                   y_title="Sekunden bis die Seite da ist", x_title="Besucher, die gleichzeitig laden",
                   colors=(S1, S2, MUTED), dashed=(2,), number_format="0.00")
        if rec:
            meaning = (f"Bis {rec['concurrency']} gleichzeitig bleibt die Seite für fast alle unter dem Ziel. "
                       + (f"Bei {steps[steps.index(rec) + 1]['concurrency']} wird es zu langsam."
                          if rec is not steps[-1] else "Die Grenze liegt oberhalb der getesteten Stufen."))
        else:
            meaning = "Schon bei der kleinsten Stufe liegt die Ladezeit über dem Ziel."
        if f["brk"]:
            meaning += f" Abbruch bei {f['brk']['concurrency']}: {f['brk']['reason']}."
        explain(sl, "Nach rechts kommen immer mehr Besucher gleichzeitig. Die blaue Linie zeigt, wie lange "
                    "ein typischer Besucher wartet, die orange, wie lange fast alle warten. Solange Orange "
                    "unter der gestrichelten Linie bleibt, ist alles gut.", meaning)
        footer(sl, "„Gleichzeitig“ heißt: so viele Seiten werden im selben Moment geladen – nicht so viele "
                   "Menschen sind auf der Website.")
        notes(sl, f"Ramp mit fester Parallelität, je Stufe {n0(cfg.get('level_seconds', 0))} s im eingeschwungenen "
                  "Zustand. Linien: Ladezeit p50 und p95. Ziel erreicht = p95 ≤ SLO und keine Fehler.")

        # ═══ Gesamtleistung ═══
        sl = d.slide()
        title(sl, "Wie viel schafft der Server insgesamt?", "Seiten pro Sekunde für alle Besucher zusammen")
        bar_chart(sl, 0.6, 1.7, 6.2, 5.0, cats, [s.get("req_s") or 0 for s in steps],
                  y_title="Seiten pro Sekunde", x_title="Besucher, die gleichzeitig laden", color=S1,
                  number_format="0.0")
        rows = [["gleichzeitig", "Seiten/s", "Ladezeit normal", "fast alle", "Fehler", "Ziel"]]
        for s in steps:
            ok = meets_slo(s, cfg)
            rows.append([str(s["concurrency"]), fmt(s.get("req_s"), 1), secs(s.get("e2e_p50")),
                         secs(s.get("e2e_p95")), fmt(s["error_rate"] * 100, 1, " %"),
                         ("erreicht", GOOD) if ok else ("verfehlt", BAD)])
        table(sl, 7.1, 1.75, 5.65, rows, col_w=[1.0, 0.85, 1.25, 0.9, 0.75, 0.9], font=10.5)
        if top:
            flat = top is not steps[-1]
            last_ok = meets_slo(steps[-1], cfg)
            text(sl, 7.1, 1.95 + 0.34 * len(rows), 5.65, 1.6, [
                f"Höchstleistung: {fmt(top.get('req_s'), 1)} Seiten pro Sekunde – das sind "
                f"{n0((top.get('req_s') or 0) * 60)} Seitenaufrufe pro Minute.",
                "Danach steigt die Leistung nicht mehr: Zusätzliche Besucher warten nur länger." if flat else
                "Die Leistung stieg bis zur letzten Stufe – der Server war noch nicht am Anschlag." if last_ok else
                "Mehr Seiten gehen zwar noch durch – aber nur, weil jeder Besucher länger wartet als gewünscht."],
                size=12.5, color=INK2, space_after=6)
        notes(sl, "Seiten/s = abgeschlossene Seitenaufrufe (inklusive aller Dateien) pro Sekunde im Messfenster.")

    # ═══ Echter Andrang ═══
    if stages:
        sl = d.slide()
        title(sl, "Echter Andrang", "Besucher kommen zufällig – mal zwei auf einmal, mal eine Weile keiner")
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, [per_min(s["rate"]) for s in stages],
                   [("normal (die Hälfte ist schneller)", [s.get("e2e_p50") for s in stages]),
                    ("fast alle (95 % sind schneller)", [s.get("e2e_p95") for s in stages]),
                    (f"Ziel: {secs(slo)}", [slo] * len(stages))],
                   y_title="Sekunden bis die Seite da ist", x_title="Seitenaufrufe pro Minute",
                   colors=(S1, S2, MUTED), dashed=(2,), number_format="0.00")
        ok = f["cap"].get("rate_ok")
        meaning = (f"Bis {per_min(ok)} Seitenaufrufe pro Minute läuft es flüssig." if ok
                   else "Schon die kleinste getestete Menge war zu viel.")
        if f["rbrk"]:
            meaning += f" Ab {per_min(f['rbrk']['rate'])} pro Minute: {f['rbrk']['reason']}."
        if users:
            meaning += (f" Daraus ergibt sich: Es reicht für ≈ {approx(users)} Besucher, wenn jeder alle "
                        f"{n0(think)} s eine Seite aufruft.")
        explain(sl, "Hier kommen die Besucher nicht im Gleichschritt, sondern zufällig wie im Alltag. So zeigt "
                    "sich, ob sich eine Warteschlange aufbaut. Nach rechts wird der Andrang größer.", meaning)
        notes(sl, "Offene Last mit Poisson-Ankünften. Überlastet = Ladezeit der letzten Besucher mehr als doppelt "
                  "so hoch wie die der ersten und über dem Ziel, oder Fehlerquote über "
                  f"{fmt(DEFAULTS['max_error_rate'] * 100, 0)} %.")

    # ═══ Großer Ansturm ═══
    if spike:
        sl = d.slide()
        title(sl, "Großer Ansturm", f"{spike['size']} Besucher im selben Augenblick – wie nach einem Newsletter")
        burst, bw = spike["burst"], (W - 1.2 - 0.5) / 3
        stat(sl, 0.6, 1.9, bw, 2.2, f"{burst['ok']} von {burst['n']}", "wurden bedient",
             "alle haben ihre Seite bekommen" if not burst["errors"] else f"{burst['errors']} bekamen eine Fehlerseite",
             color=GOOD if not burst["errors"] else BAD, vsize=36)
        stat(sl, 0.6 + bw + 0.25, 1.9, bw, 2.2, secs(burst.get("e2e_max")), "längste Ladezeit",
             time_feel(burst.get("e2e_max")), vsize=36)
        crashed, back = spike.get("crashed"), spike.get("recovered")
        stat(sl, 0.6 + 2 * (bw + 0.25), 1.9, bw, 2.2,
             "ausgefallen" if crashed else "ja" if back else "nein" if back is False else "–",
             "danach wieder normal?",
             "die Website war nicht mehr erreichbar" if crashed else
             "kurz darauf so schnell wie vor dem Ansturm" if back else "blieb langsamer als vorher",
             color=BAD if crashed else GOOD if back else WARN, vsize=36)
        rect(sl, 0.6, 4.45, W - 1.2, 1.7, PANEL)
        text(sl, 0.9, 4.65, W - 1.8, 0.35, "Was das bedeutet", size=14, bold=True, color=S1)
        text(sl, 0.9, 5.05, W - 1.8, 1.0,
             "Ein Ansturm ist härter als gleichmäßige Last: Alle kommen im selben Moment, der Server hat keine "
             "Zeit, sich einzuschwingen. Wichtig ist weniger die Wartezeit im Ansturm als die Frage, ob jemand "
             "abgewiesen wurde und ob sich die Website danach erholt.", size=13, color=INK)
        notes(sl, f"Burst: {burst['n']} Aufrufe gleichzeitig gestartet. Ladezeit p50 {fmt(burst.get('e2e_p50'), 2)} s, "
                  f"p95 {fmt(burst.get('e2e_p95'), 2)} s. Erholung: 3 Aufrufe nacheinander, verglichen mit der Baseline "
                  "(höchstens 1,5-fache Ladezeit).")

    # ═══ Ausdauer ═══
    if soak:
        sl = d.slide()
        title(sl, "Ausdauer", f"{mins(soak['minutes'])} gleichmäßige Last mit {soak['concurrency']} gleichzeitig")
        buckets = [b for b in soak.get("buckets") or [] if b.get("s")]
        deg = soak.get("degradation") or {}
        slower = deg.get("ttft_change_pct")
        if len(buckets) >= 2:
            line_chart(sl, 0.6, 1.7, 8.1, 5.0, [fmt(b["t_min"], 1) for b in buckets],
                       [("Ladezeit (normal)", [b["s"].get("e2e_p50") for b in buckets]),
                        (f"Ziel: {secs(slo)}", [slo] * len(buckets))],
                       y_title="Sekunden bis die Seite da ist", x_title="Minuten seit Beginn",
                       colors=(S1, MUTED), dashed=(1,), number_format="0.00")
        else:
            stat(sl, 0.6, 1.9, 8.1, 2.2, secs(soak["total"].get("e2e_p50")), "Ladezeit unter Dauerlast",
                 time_feel(soak["total"].get("e2e_p50")), vsize=36)
        meaning = ("Die Seite blieb über die ganze Zeit gleich schnell." if slower is None or abs(slower) < 5
                   else f"Am Ende war die Ladezeit {signed(slower)} gegenüber dem Anfang."
                   + (" Das deutet auf ein Problem hin, das mit der Zeit wächst." if slower > 25 else ""))
        if soak["total"]["errors"]:
            meaning += f" Dabei gab es {soak['total']['errors']} Fehler."
        ctl_note = control_note(summary)
        if ctl_note:
            meaning += (" Die Kontrollmessung ganz am Ende – wieder ein Besucher allein: " + ctl_note[1] + ".")
        explain(sl, "Die Linie zeigt die Ladezeit über die Dauer des Tests. Sie soll waagerecht bleiben. "
                    "Steigt sie an, geht dem Server mit der Zeit etwas aus – zum Beispiel Speicher oder "
                    "Datenbankverbindungen.", meaning)
        notes(sl, f"Soak: {soak['total']['n']} Aufrufe, Fehlerquote {fmt(soak['total']['error_rate'] * 100, 2)} %. "
                  "Vergleich erstes gegen letztes Drittel: Durchsatz "
                  f"{signed(deg.get('tps_change_pct'))}, Ladezeit p50 {signed(slower)}.")

    # ═══ Alles auf einen Blick ═══
    sl = d.slide()
    title(sl, "Alles auf einen Blick")
    rect(sl, 0.6, 1.5, 3.7, 5.2, DARK_BG)
    text(sl, 0.9, 1.8, 3.1, 0.4, "REICHT FÜR", size=13, bold=True, color="94A3B8")
    text(sl, 0.9, 2.3, 3.1, 1.3, f"≈ {approx(users)}" if users else "–", size=60, bold=True, color="FFFFFF",
         font="Cambria")
    text(sl, 0.9, 3.75, 3.1, 0.8, "Besucher gleichzeitig auf der Website", size=16, color="CBD5E1")
    text(sl, 0.9, 4.9, 3.1, 1.6,
         (f"Erwartet: {n0(f['target'])}. " if f["target"] else "")
         + f"Wenn jeder etwa alle {n0(think)} s eine Seite aufruft.", size=12.5, color="94A3B8")
    rows = result_rows(summary)
    rh = min(0.52, 5.2 / max(1, len(rows)))
    for i, (col, area, res) in enumerate(rows):
        yy = 1.5 + i * rh
        dot(sl, 4.65, yy + 0.1, 0.22, col)
        text(sl, 5.05, yy + 0.04, 2.6, rh, area, size=13, bold=True)
        text(sl, 7.7, yy + 0.04, 5.05, rh, res, size=12.5, color=INK2)
    if not rows:
        text(sl, 4.65, 1.6, 8.0, 1.0, vd["headline"], size=16, color=INK2)
    notes(sl, "Dieselben Zeilen stehen im einseitigen PDF-Kurzbericht.")

    # ═══ Ansatzpunkte ═══
    if steps or base:
        sl = d.slide()
        title(sl, "Wo man ansetzen kann", "Mögliche nächste Schritte – abgeleitet aus den Messwerten")
        _bullets(sl, 0.6, 1.85, W - 1.2, pointers(summary), gap=1.15)
        footer(sl, "Der Test zeigt, wo es hakt – nicht, warum. Die Ursache klärt ein Blick in Server und Anwendung.")
        notes(sl, f"Regeln: erste Antwort ohne Last über {fmt(GOOD_TTFB, 1)} s; Seitengewicht über "
                  f"{size(LIGHT_PAGE)}; Stufe nach dem Sweet Spot verfehlt das Ziel; Kapazität unter dem "
                  "erwarteten Andrang; Fehler im Ansturm.")

    # ═══ Annahmen und Grenzen ═══
    sl = d.slide()
    title(sl, "Annahmen und Grenzen", "Was die Zahlen aussagen – und was nicht")
    rect(sl, 0.6, 1.7, 5.95, 3.9, CARD)
    text(sl, 0.9, 1.9, 5.35, 0.4, "Annahmen", size=15, bold=True, color=S1)
    text(sl, 0.9, 2.4, 5.35, 4.0, [
        f"• Ein Besucher ruft etwa alle {n0(think)} s eine Seite auf. Klickt er häufiger, reicht es für weniger.",
        f"• Als „geladen“ gilt die Seite, wenn fast alle (95 %) sie nach höchstens {secs(slo)} haben.",
        "• Jeder Besucher kommt zum ersten Mal: ohne Browser-Cache, mit eigenen Verbindungen. Das ist der "
        "ungünstige Fall.",
        "• Getestet wurde genau eine Adresse. Andere Seiten können schwerer oder leichter sein.",
    ], size=12.5, color=INK, space_after=7)
    rect(sl, 6.8, 1.7, 5.95, 3.9, CARD)
    text(sl, 7.1, 1.9, 5.35, 0.4, "Nicht gemessen", size=15, bold=True, color=S2)
    text(sl, 7.1, 2.4, 5.35, 4.0, [
        "• Inhalte fremder Server: Schriften, Karten, Videos, Werbung, Statistik-Dienste.",
        "• Die Zeit, die der Browser zum Aufbauen und Darstellen braucht – und alles, was erst per "
        "JavaScript nachgeladen wird.",
        "• Abläufe über mehrere Seiten: Anmelden, Suchen, Warenkorb, Bezahlen.",
        "• Die Internetverbindung der echten Besucher. Gemessen wurde vom Messrechner aus.",
    ], size=12.5, color=INK, space_after=7)
    q_items = (summary.get("quality") or {}).get("items") or []
    if q_items:
        text(sl, 0.6, 5.8, 4.0, 0.35, "Wie verlässlich ist die Messung?", size=13, bold=True, color=S1)
        col_w = (W - 1.2) / len(q_items[:3])
        for i, item in enumerate(q_items[:3]):
            dot(sl, 0.62 + i * col_w, 6.27, 0.18, STATUS[item["status"]])
            text(sl, 0.92 + i * col_w, 6.2, col_w - 0.45, 0.6,
                 [[(item["title"] + " ", {"bold": True}), item["value"]]], size=11.5, color=INK2)
    footer(sl, " · ".join(x for x in (host_line(summary),
                                      "Rohdaten: summary.json und raw_requests.jsonl im Ergebnisordner") if x))
    notes(sl, "Kapazität nach dem Gesetz von Little: Besucher = Seiten/s × (mittlere Ladezeit + Pause zwischen "
              "zwei Klicks); bevorzugt aus der offenen Last (Echter Andrang), sonst aus dem Stufentest.")

    d.save(path)
    return path


# ════════════════════════════════════════════════════════════════════════════
#  PDF – eine A4-Seite
# ════════════════════════════════════════════════════════════════════════════

def build_pdf(summary, path):
    from reportlab.lib.colors import HexColor

    from report_pdf import M, PH, PW, Page, chart

    pg = Page(path)
    c = pg.c
    f = facts(summary)
    cfg, slo, vd = f["cfg"], f["slo"], f["verdict"]
    steps, stages = f["steps"], f["stages"]
    cw = PW - 2 * M
    y = PH - M

    pg.text(M, y - 8, "LASTTEST WEBSITE · KURZBERICHT", 7.5, True, MUTED)
    pg.text(M, y - 30, "Wie viele Besucher hält unsere Website aus?", 19, True)
    started = when(summary)
    pg.text(M, y - 45, " · ".join(x for x in (cfg.get("base_url", ""), f"getestet am {started}" if started else "") if x),
            8.5, color=INK2)
    y -= 58

    pg.box(M, y - 32, cw, 32, STATUS[vd["status"]])
    pg.text(M + 12, y - 21, vd["headline"], 14, True, "FFFFFF")
    y -= 42

    cards = headline_cards(summary)
    if cards:
        gap = 8
        bw = (cw - gap * (len(cards) - 1)) / len(cards)
        for i, (v, lbl, mean_, col) in enumerate(cards):
            bx = M + i * (bw + gap)
            pg.box(bx, y - 66, bw, 66, "F1F5F9")
            pg.text(bx + 9, y - 25, v, 18, True, col)
            pg.para(bx + 9, y - 30, bw - 18, lbl, 8, True, INK2, max_lines=1)
            pg.para(bx + 9, y - 41, bw - 18, mean_, 7, color=MUTED, max_lines=2)
        y -= 78

    if vd["reasons"]:
        pg.text(M, y - 10, "Warum?", 10, True, S1)
        y -= 15
        for st, t_ in vd["reasons"][:5]:
            pg.dot(M + 1, y - 9, 6, STATUS[st])
            y = pg.para(M + 13, y, cw - 13, t_, 8.5, max_lines=1) - 2.5
        y -= 6

    rows = result_rows(summary)
    foot_top = M + 44
    if steps:
        ch_h = max(140, min(230, y - foot_top - 26 - len(rows) * 16 - 18))
        half = (cw - 14) / 2
        if stages:
            chart(pg, M, y - ch_h, half, ch_h, "Ladezeit, wenn die Besucher zufällig kommen",
                  [("normal", S1, [(s["rate"] * 60, s.get("e2e_p50")) for s in stages]),
                   ("fast alle", S2, [(s["rate"] * 60, s.get("e2e_p95")) for s in stages])],
                  "Seitenaufrufe pro Minute", "Sekunden bis die Seite da ist", slo, f"Ziel ≤ {fmt(slo, 1)} s", 1)
        else:
            chart(pg, M, y - ch_h, half, ch_h, "Ladezeit bei zunehmendem Andrang",
                  [("normal", S1, [(s["concurrency"], s.get("e2e_p50")) for s in steps]),
                   ("fast alle", S2, [(s["concurrency"], s.get("e2e_p95")) for s in steps])],
                  "Besucher gleichzeitig", "Sekunden bis die Seite da ist", slo, f"Ziel ≤ {fmt(slo, 1)} s", 1)
        chart(pg, M + half + 14, y - ch_h, half, ch_h, "Gesamtleistung",
              [("alle zusammen", S1, [(s["concurrency"], s.get("req_s")) for s in steps])],
              "Besucher gleichzeitig", "Seiten pro Sekunde", dec=1)
        y -= ch_h + 12

    if rows:
        pg.text(M, y - 10, "Alle Ergebnisse", 10, True, S1)
        y -= 16
        rh = max(11.5, min(16, (y - foot_top) / len(rows)))
        for i, (col, area, res) in enumerate(rows[:int((y - foot_top) // rh)]):
            yy = y - (i + 1) * rh
            if i % 2 == 0:
                c.setFillColor(HexColor("#F8FAFC"))
                c.rect(M, yy, cw, rh, stroke=0, fill=1)
            pg.dot(M + 5, yy + rh / 2 - 3, 6, col)
            pg.text(M + 17, yy + rh / 2 - 3, area, 8.5, True)
            pg.para(M + 150, yy + rh / 2 + 5.2, cw - 155, res, 8.5, color=INK2, max_lines=1)

    pre = f["pre"]
    foot = [f"Besucher gleichzeitig nach dem Gesetz von Little bei {n0(f['think'])} s Pause zwischen zwei Klicks – "
            "eine Schätzung, keine Garantie. Jeder simulierte Besucher lädt die Seite"
            + (f" und {n0(pre['assets'])} Dateien derselben Website" if pre.get("assets") else "")
            + " wie beim ersten Besuch (ohne Cache).",
            "Nicht gemessen: Inhalte fremder Server, die Darstellung im Browser, Abläufe über mehrere Seiten."]
    c.setStrokeColor(HexColor("#E5E7EB"))
    c.line(M, foot_top - 4, M + cw, foot_top - 4)
    yy = foot_top - 8
    for t_ in foot:
        yy = pg.para(M, yy, cw, t_, 6.8, color=MUTED, max_lines=2) - 1
    pg.text(M + cw, M - 12, "Erstellt mit LAST · Details in der PowerPoint", 6.5, color=MUTED, align="right")
    c.setTitle("Lasttest Website – Kurzbericht")
    c.setAuthor("LAST")
    c.showPage()
    c.save()
    return path


# ════════════════════════════════════════════════════════════════════════════
#  Vergleich mehrerer Läufe
# ════════════════════════════════════════════════════════════════════════════

def _label(summary):
    return when(summary) or "Lauf"


def _figures(summary):
    """Vergleichbare Kennzahlen eines Laufs: (Name, Wert, Anzeige, höher ist besser)."""
    f = facts(summary)
    base, rec, top = f["base"] or {}, f["rec"], f["top"] or {}
    peak = (top.get("req_s") or 0) * 60 or None
    return [
        ("Besucher gleichzeitig", f["users"], f"≈ {approx(f['users'])}" if f["users"] else "–", True),
        ("Ladezeit ohne Andrang", base.get("e2e_p50"), secs(base.get("e2e_p50")), False),
        ("Erste Antwort des Servers", base.get("ttft_p50"), secs(base.get("ttft_p50")), False),
        ("Gleichzeitig ohne Frust", rec["concurrency"] if rec else None, str(rec["concurrency"]) if rec else "–", True),
        ("Seitenaufrufe pro Minute (Höchstleistung)", peak, n0(peak) if peak else "–", True),
        ("Gewicht eines Besuchs", f["pre"].get("total_bytes"), size(f["pre"].get("total_bytes")), False),
    ]


def _change(ref, v, higher_better):
    """(Text, Farbe) für die Veränderung gegenüber dem ersten Lauf."""
    if ref is None or v is None or not ref:
        return "–", MUTED
    p = (v / ref - 1) * 100
    if abs(p) < 3:
        return "gleich", MUTED
    return signed(p), GOOD if (p > 0) == higher_better else BAD


def build_compare(summaries, path, labels=None):
    labels = list(labels or [])
    labels += [_label(s) for s in summaries[len(labels):]]
    d = Deck()
    colors = (S1, S2, S3, S4)
    figs = [_figures(s) for s in summaries]
    urls = sorted({(s.get("config") or {}).get("base_url", "") for s in summaries})

    sl = d.slide(dark=True)
    text(sl, 0.8, 1.55, 11.5, 0.45, "VERGLEICH", size=15, color="94A3B8", bold=True)
    text(sl, 0.8, 2.0, 11.8, 1.0, "Ist die Website schneller geworden?", size=40, color="FFFFFF", bold=True,
         font="Cambria")
    text(sl, 0.8, 3.05, 11.8, 0.6, " · ".join(urls), size=22, color="CBD5E1")
    for i, lbl in enumerate(labels):
        dot(sl, 0.8, 4.48 + i * 0.42, 0.2, colors[i % 4])
        text(sl, 1.15, 4.4 + i * 0.42, 11, 0.4, lbl + ("  (Referenz)" if i == 0 else ""), size=15, color="CBD5E1")
    notes(sl, "Automatisch erzeugt von report_web.py. Der älteste Lauf ist die Referenz.")

    sl = d.slide()
    title(sl, "Die wichtigsten Zahlen", f"Veränderung von „{labels[-1]}“ gegenüber „{labels[0]}“")
    rows = [["", *labels, "Veränderung"]]
    for i, (name, ref, _, higher) in enumerate(figs[0]):
        rows.append([name, *[fg[i][2] for fg in figs], _change(ref, figs[-1][i][1], higher)])
    lw = 4.2
    cw = (W - 1.2 - lw - 1.7) / len(labels)
    table(sl, 0.6, 1.8, W - 1.2, rows, col_w=[lw, *[cw] * len(labels), 1.7], font=13, row_h=0.5)
    if len(urls) > 1:
        footer(sl, "Achtung: Die Läufe haben unterschiedliche Adressen getestet – die Zahlen sind nur bedingt vergleichbar.")
    else:
        footer(sl, "Grün = besser als die Referenz, Rot = schlechter. Unterschiede unter 3 % gelten als gleich.")
    notes(sl, "Besucher nach dem Gesetz von Little; Ladezeit und erste Antwort jeweils p50 ohne Last; "
              "Höchstleistung = größter gemessener Durchsatz im Stufentest.")

    cats = sorted({st["concurrency"] for s in summaries for st in (s.get("ramp") or {}).get("steps", [])})
    if cats:
        def series(key):
            out = []
            for lbl, s in zip(labels, summaries):
                by_c = {st["concurrency"]: st.get(key) for st in (s.get("ramp") or {}).get("steps", [])}
                out.append((lbl, [by_c.get(c) for c in cats]))
            return out

        slo = facts(summaries[0])["slo"]
        sl = d.slide()
        title(sl, "Ladezeit bei zunehmendem Andrang", "So lange warten fast alle Besucher (95 %)")
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, cats, series("e2e_p95") + [(f"Ziel: {secs(slo)}", [slo] * len(cats))],
                   y_title="Sekunden bis die Seite da ist", x_title="Besucher, die gleichzeitig laden",
                   colors=(*colors[:len(labels)], MUTED), dashed=(len(labels),), number_format="0.00")
        explain(sl, "Jede Linie ist ein Lauf. Je tiefer eine Linie liegt, desto schneller war die Seite. "
                    "Wichtig ist, wie lange sie unter der gestrichelten Ziel-Linie bleibt.",
                "Liegt die neue Linie durchgehend unter der alten, hat die Änderung geholfen – auch unter Last, "
                "nicht nur im Leerlauf.")
        notes(sl, "Ladezeit p95 je Stufe des Stufentests.")

        sl = d.slide()
        title(sl, "Gesamtleistung", "Seiten pro Sekunde für alle Besucher zusammen")
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, cats, series("req_s"), y_title="Seiten pro Sekunde",
                   x_title="Besucher, die gleichzeitig laden", colors=colors, number_format="0.0")
        explain(sl, "Je höher eine Linie liegt, desto mehr Seiten liefert der Server pro Sekunde aus. "
                    "Wo sie flach wird, ist er am Anschlag.",
                "Eine höhere Linie bedeutet: Derselbe Server bedient mehr Besucher.")
        notes(sl, "Durchsatz (abgeschlossene Seitenaufrufe pro Sekunde) je Stufe.")

    sl = d.slide()
    title(sl, "Fazit")
    better = [n for (n, ref, _, hb), cur in zip(figs[0], figs[-1]) if _change(ref, cur[1], hb)[1] == GOOD]
    worse = [n for (n, ref, _, hb), cur in zip(figs[0], figs[-1]) if _change(ref, cur[1], hb)[1] == BAD]
    v0, v1 = verdict(summaries[0]), verdict(summaries[-1])
    for i, (lbl, v) in enumerate(((labels[0], v0), (labels[-1], v1))):
        rect(sl, 0.6 + i * 6.2, 1.5, 5.95, 1.3, STATUS[v["status"]])
        text(sl, 0.9 + i * 6.2, 1.62, 5.35, 0.35, lbl, size=13, bold=True, color="FFFFFF")
        text(sl, 0.9 + i * 6.2, 2.0, 5.35, 0.7, v["headline"], size=17, bold=True, color="FFFFFF", font="Cambria")
    text(sl, 0.6, 3.2, W - 1.2, 3.2, [
        [("Besser geworden: ", {"bold": True, "color": GOOD}), ", ".join(better) or "nichts Messbares"],
        [("Schlechter geworden: ", {"bold": True, "color": BAD}), ", ".join(worse) or "nichts Messbares"],
        "Kleine Unterschiede können Zufall sein – Ladezeiten schwanken von Lauf zu Lauf um einige Prozent.",
    ], size=15, color=INK, space_after=10)
    notes(sl, "Vergleich des letzten mit dem ersten Lauf; Schwelle 3 %.")

    d.save(path)
    return path


def build_comparison(dirs, path, labels=None):
    """Vergleichsbericht aus mehreren Ergebnisordnern – Gegenstück zu llm_stresstest.build_comparison."""
    summaries = []
    for d in dirs:
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as fh:
            summaries.append(json.load(fh))
    return build_compare(summaries, path, labels)
