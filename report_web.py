"""
Berichte für den Lasttest von Websites und HTTP-APIs – in einfacher Sprache.

  build_report      PowerPoint mit allen Ergebnissen
  build_pdf         Kurzbericht auf einer A4-Seite
  build_compare     Vergleich zweier oder mehrerer Läufe (z. B. vorher / nachher)

Website: Die Website ist ein Laden. Jeder Besucher kommt herein, schaut sich das Schaufenster an
(die Seite) und wartet, bis alles ausgepackt ist (Bilder, Styles, Skripte).
API: Die API ist ein Schalter. Jede Anfrage ist ein Kunde, der eine Auskunft will, und gemessen
wird, wie lange er auf die Antwort wartet.

Alle Formulierungen, die sich zwischen beiden unterscheiden, stehen in TEXTS. Gestaltung und
Bausteine kommen aus report_pptx.py und report_pdf.py, damit alle Berichte gleich aussehen.
"""

import datetime as dt
import json
import os
import re

from pptx.enum.text import MSO_ANCHOR
from pptx.util import Inches

from llm_stresstest import IN_DOCKER, fmt, round_users
from report_pptx import (
    BAD,
    CARD,
    DARK_BG,
    GOOD,
    INFO,
    INK,
    INK2,
    MUTED,
    PANEL,
    S1,
    S2,
    S3,
    S4,
    STATUS,
    WARN,
    Deck,
    W,
    bar_chart,
    dot,
    explain,
    footer,
    line_chart,
    mins,
    n0,
    notes,
    per_min,
    rect,
    secs,
    stat,
    table,
    text,
    time_feel,
    title,
)
from web_stresstest import DEFAULTS, capacity, meets_slo, verdict

GOOD_TTFB, SLOW_TTFB = 0.5, 1.5            # Richtwerte für die erste Antwort des Servers (s)
LIGHT_PAGE, HEAVY_PAGE = 2e6, 5e6          # Richtwerte für das Gewicht einer Seite (Bytes)

# ── Begriffe je Testart ────────────────────────────────────────────────────
TEXTS = {
    "web": {
        "title": "Wie viele Besucher hält unsere Website aus?",
        "compare_title": "Ist die Website schneller geworden?",
        "subject": "die Website", "Subject": "Die Website",
        "units": "Besucher", "unit_label": "Besucher gleichzeitig",
        "capacity_label": "Besucher gleichzeitig auf der Website",
        "time": "Ladezeit", "time_alone": "Ladezeit ohne Andrang",
        "time_long": "Ladezeit der ganzen Seite",
        "y_axis": "Sekunden bis die Seite da ist", "x_axis": "Besucher, die gleichzeitig laden",
        "rate_axis": "Seitenaufrufe pro Minute", "per_min": "Aufrufe/min", "per_min_long": "Seitenaufrufe pro Minute",
        "throughput": "Seiten pro Sekunde", "throughput_short": "Seiten/s",
        "done": "bis die Seite komplett da ist", "ready": "haben die Seite",
        "served": "alle haben ihre Seite bekommen", "fail": "bekamen eine Fehlerseite",
        "alone_sub": "So schnell ist die Seite, wenn sonst niemand da ist",
        "ramp_sub": "Ab wann wird die Seite zäh?",
        "rate_sub": "Besucher kommen zufällig – mal zwei auf einmal, mal eine Weile keiner",
        "spike_sub": "{n} Besucher im selben Augenblick – wie nach einem Newsletter",
        "zaeh": "bis {c} Besucher laden gleichzeitig, ohne dass es zäh wird",
        "zaeh_none": "schon bei der kleinsten Stufe lädt die Seite zu langsam",
        "capacity_note": "Besucherzahl nach dem Gesetz von Little bei {think} s Pause zwischen zwei Klicks – "
                         "eine Schätzung, keine Garantie.",
        "capacity_sub": "Wenn jeder etwa alle {think} s eine Seite aufruft.",
        "pause": "zwischen zwei Klicks", "one": "Besucher",
        "gleichzeitig_note": "„Gleichzeitig“ heißt: so viele Seiten werden im selben Moment geladen – nicht so viele "
                             "Menschen sind auf der Website.",
        "rate_meaning_users": " Daraus ergibt sich: Es reicht für ≈ {users} Besucher, wenn jeder alle {think} s eine Seite aufruft.",
        "best_case": "Schneller als hier wird die Seite unter Last nie – das ist der beste Fall.",
        "flat": "Danach steigt die Leistung nicht mehr: Zusätzliche Besucher warten nur länger.",
        "more_but_slow": "Mehr Seiten gehen zwar noch durch – aber nur, weil jeder Besucher länger wartet als gewünscht.",
        "soak_stable": "Die Seite blieb über die ganze Zeit gleich schnell.",
        "control_intro": " Die Kontrollmessung ganz am Ende – wieder ein Besucher allein: ",
        "pointer_slow": ("Der Server braucht schon ohne Andrang lange für die erste Antwort",
                         "{t}, bevor überhaupt etwas kommt. Oft hilft es, fertige Seiten zwischenzuspeichern "
                         "(Seiten-Cache), statt sie für jeden Besucher neu zu bauen."),
        "pointer_few": ("Schon wenige Besucher sind zu viel",
                        "Bevor mehr Leistung gekauft wird, zuerst die Ladezeit ohne Andrang senken – sie ist die "
                        "Untergrenze für alles Weitere."),
        "pointer_gap": ("Zwischen {a} und {b} gleichzeitig wird es eng",
                        "Vor Aktionen, Newslettern oder Fernsehauftritten einplanen: mehr Serverleistung, ein "
                        "vorgeschaltetes Auslieferungsnetz (CDN) oder ein Seiten-Cache."),
        "pointer_target": ("Die erwartete Besucherzahl wird nicht erreicht",
                           "Es reicht für ≈ {users}, erwartet werden {target}. Die Lücke lässt sich nur mit "
                           "schnellerer Seite oder mehr Leistung schließen."),
        "pointer_ok": ("Kein dringender Handlungsbedarf",
                       "Die Website erreicht alle gesetzten Ziele. Sinnvoll ist, den Test nach größeren Änderungen "
                       "zu wiederholen und die Läufe zu vergleichen."),
        "assumptions": ["• Ein Besucher ruft etwa alle {think} s eine Seite auf. Klickt er häufiger, reicht es für weniger.",
                        "• Als „geladen“ gilt die Seite, wenn fast alle (95 %) sie nach höchstens {slo} haben.",
                        "• Jeder Besucher kommt zum ersten Mal: ohne Browser-Cache, mit eigenen Verbindungen. Das ist "
                        "der ungünstige Fall.",
                        "• Getestet wurde genau eine Adresse. Andere Seiten können schwerer oder leichter sein."],
        "not_measured": ["• Inhalte fremder Server: Schriften, Karten, Videos, Werbung, Statistik-Dienste.",
                         "• Die Zeit, die der Browser zum Aufbauen und Darstellen braucht – und alles, was erst per "
                         "JavaScript nachgeladen wird.",
                         "• Abläufe über mehrere Seiten: Anmelden, Suchen, Warenkorb, Bezahlen.",
                         "• Die Internetverbindung der echten Besucher. Gemessen wurde vom Messrechner aus."],
        "pdf_kicker": "LASTTEST WEBSITE · KURZBERICHT",
        "pdf_foot": "Besucher gleichzeitig nach dem Gesetz von Little bei {think} s Pause zwischen zwei Klicks – "
                    "eine Schätzung, keine Garantie. Jeder simulierte Besucher lädt die Seite{files} wie beim "
                    "ersten Besuch (ohne Cache).",
        "pdf_foot2": "Nicht gemessen: Inhalte fremder Server, die Darstellung im Browser, Abläufe über mehrere Seiten.",
        "compare_hint": "Liegt die neue Linie durchgehend unter der alten, hat die Änderung geholfen – auch unter "
                        "Last, nicht nur im Leerlauf.",
        "compare_more": "Eine höhere Linie bedeutet: Derselbe Server bedient mehr Besucher.",
        "little": "Kapazität nach dem Gesetz von Little: Besucher = Seiten/s × (mittlere Ladezeit + Pause zwischen "
                  "zwei Klicks); bevorzugt aus der offenen Last (Echter Andrang), sonst aus dem Stufentest.",
    },
    "flow": {
        "title": "Wie viele Nutzer hält unsere Anwendung aus?",
        "compare_title": "Ist die Anwendung schneller geworden?",
        "subject": "die Anwendung", "Subject": "Die Anwendung",
        "units": "Nutzer", "unit_label": "Nutzer gleichzeitig",
        "capacity_label": "Nutzer gleichzeitig in der Anwendung",
        "time": "Antwortzeit", "time_alone": "Antwortzeit ohne Andrang",
        "time_long": "Antwortzeit des ganzen Ablaufs",
        "y_axis": "Sekunden bis die Antwort da ist", "x_axis": "Nutzer, die gleichzeitig den Ablauf machen",
        "rate_axis": "Durchläufe pro Minute", "per_min": "Durchläufe/min", "per_min_long": "Durchläufe pro Minute",
        "throughput": "Durchläufe pro Sekunde", "throughput_short": "Durchl./s",
        "done": "bis die Antwort komplett da ist", "ready": "haben ihre Antwort",
        "served": "alle haben ihre Antwort bekommen", "fail": "bekamen einen Fehler",
        "alone_sub": "So schnell antwortet die Anwendung, wenn sonst niemand da ist",
        "ramp_sub": "Ab wann wird die Anwendung zäh?",
        "rate_sub": "Nutzer kommen zufällig – mal zwei auf einmal, mal eine Weile keiner",
        "spike_sub": "{n} Nutzer im selben Augenblick – wie zu Beginn einer Schulung",
        "zaeh": "bis {c} Nutzer machen den Ablauf gleichzeitig, ohne dass es zäh wird",
        "zaeh_none": "schon bei der kleinsten Stufe antwortet die Anwendung zu langsam",
        "capacity_note": "Nutzerzahl nach dem Gesetz von Little bei {think} s Pause zwischen zwei Durchläufen eines "
                         "Nutzers – eine Schätzung, keine Garantie.",
        "capacity_sub": "Wenn jeder etwa alle {think} s den Ablauf einmal macht.",
        "pause": "zwischen zwei Durchläufen", "one": "Nutzer",
        "gleichzeitig_note": "„Gleichzeitig“ heißt: so viele Durchläufe laufen im selben Moment – nicht so viele "
                             "Menschen sind angemeldet.",
        "rate_meaning_users": " Daraus ergibt sich: Es reicht für ≈ {users} Nutzer, wenn jeder alle {think} s den Ablauf macht.",
        "best_case": "Schneller als hier antwortet die Anwendung unter Last nie – das ist der beste Fall.",
        "flat": "Danach steigt die Leistung nicht mehr: Zusätzliche Nutzer warten nur länger.",
        "more_but_slow": "Mehr Durchläufe gehen zwar noch durch – aber nur, weil jeder Nutzer länger wartet als gewünscht.",
        "soak_stable": "Die Anwendung blieb über die ganze Zeit gleich schnell.",
        "control_intro": " Die Kontrollmessung ganz am Ende – wieder ein Nutzer allein: ",
        "pointer_slow": ("Die Anwendung braucht schon ohne Andrang lange für die erste Antwort",
                         "{t}, bevor überhaupt etwas kommt. Bei einem KI-Chat steckt die Zeit meist im Modell selbst "
                         "oder in der Vorverarbeitung – dort zuerst messen."),
        "pointer_few": ("Schon wenige Nutzer sind zu viel",
                        "Bevor mehr Leistung gekauft wird, zuerst die Antwortzeit ohne Andrang senken – sie ist die "
                        "Untergrenze für alles Weitere."),
        "pointer_gap": ("Zwischen {a} und {b} gleichzeitig wird es eng",
                        "Vor Schulungen, Einführungen oder Aktionen einplanen: mehr Leistung für den Dienst hinter dem "
                        "Ablauf oder eine Warteschlange, die Nutzer freundlich vertröstet."),
        "pointer_target": ("Die erwartete Nutzerzahl wird nicht erreicht",
                           "Es reicht für ≈ {users}, erwartet werden {target}. Die Lücke lässt sich nur mit schnelleren "
                           "Antworten oder mehr Leistung schließen."),
        "pointer_ok": ("Kein dringender Handlungsbedarf",
                       "Die Anwendung erreicht alle gesetzten Ziele. Sinnvoll ist, den Test nach größeren Änderungen "
                       "zu wiederholen und die Läufe zu vergleichen."),
        "assumptions": ["• Ein Nutzer macht den Ablauf etwa alle {think} s einmal. Macht er ihn häufiger, reicht es für weniger.",
                        "• Als „rechtzeitig“ gilt die Antwort, wenn fast alle (95 %) sie nach höchstens {slo} haben.",
                        "• Unter Last werden die aufgezeichneten Anfragen abgespielt, nicht der Browser – der Server sieht "
                        "dieselben Anfragen, die Darstellung im Browser fehlt.",
                        "• Alle simulierten Nutzer teilen sich die Sitzung der Aufzeichnung (ein Konto)."],
        "not_measured": ["• Die Zeit, die der Browser zum Aufbauen und Darstellen braucht.",
                         "• Die Anmeldung selbst – sie liegt vor „messen ab hier“ und wurde nur einmal gemacht.",
                         "• Andere Abläufe und Seiten der Anwendung.",
                         "• Die Internetverbindung der echten Nutzer. Gemessen wurde vom Messrechner aus."],
        "pdf_kicker": "LASTTEST ABLAUF · KURZBERICHT",
        "pdf_foot": "Nutzer gleichzeitig nach dem Gesetz von Little bei {think} s Pause zwischen zwei Durchläufen – eine "
                    "Schätzung, keine Garantie. Aufgezeichnet im Browser, abgespielt per HTTP mit einer geteilten Sitzung.",
        "pdf_foot2": "Nicht gemessen: die Darstellung im Browser, die Anmeldung, andere Abläufe.",
        "compare_hint": "Liegt die neue Linie durchgehend unter der alten, hat die Änderung geholfen – auch unter "
                        "Last, nicht nur im Leerlauf.",
        "compare_more": "Eine höhere Linie bedeutet: Dieselbe Anwendung bedient mehr Nutzer.",
        "little": "Kapazität nach dem Gesetz von Little: Nutzer = Durchläufe/s × (mittlere Antwortzeit + Pause zwischen "
                  "zwei Durchläufen); bevorzugt aus der offenen Last (Echter Andrang), sonst aus dem Stufentest.",
    },
    "api": {
        "title": "Wie viele Anfragen hält unsere API aus?",
        "compare_title": "Ist die API schneller geworden?",
        "subject": "die API", "Subject": "Die API",
        "units": "Anfragen", "unit_label": "Anfragen pro Minute",
        "capacity_label": "Anfragen pro Minute, die flüssig durchgehen",
        "time": "Antwortzeit", "time_alone": "Antwortzeit ohne Last",
        "time_long": "Antwortzeit der ganzen Anfrage",
        "y_axis": "Sekunden bis die Antwort da ist", "x_axis": "Anfragen, die gleichzeitig laufen",
        "rate_axis": "Anfragen pro Minute", "per_min": "Anfragen/min", "per_min_long": "Anfragen pro Minute",
        "throughput": "Anfragen pro Sekunde", "throughput_short": "Anfr./s",
        "done": "bis die Antwort komplett da ist", "ready": "haben ihre Antwort",
        "served": "alle haben ihre Antwort bekommen", "fail": "bekamen einen Fehler",
        "alone_sub": "So schnell antwortet die API, wenn sonst niemand fragt",
        "ramp_sub": "Ab wann wird die API zäh?",
        "rate_sub": "Anfragen kommen zufällig – mal zwei auf einmal, mal eine Weile keine",
        "spike_sub": "{n} Anfragen im selben Augenblick – wie bei einem Stapellauf",
        "zaeh": "bis {c} Anfragen laufen gleichzeitig, ohne dass es zäh wird",
        "zaeh_none": "schon bei der kleinsten Stufe antwortet die API zu langsam",
        "capacity_note": "Anfragen pro Minute = höchste zufällig verteilte Last, bei der Antwortzeit und Fehlerquote "
                         "im Ziel bleiben – eine Messung bei dieser Anfrage, keine Garantie für andere.",
        "capacity_sub": "Bei zufällig verteilten Anfragen, so wie im Alltag.",
        "gleichzeitig_note": "„Gleichzeitig“ heißt: so viele Anfragen sind im selben Moment unterwegs – nicht so viele "
                             "Programme oder Nutzer verwenden die API.",
        "rate_meaning_users": "",
        "best_case": "Schneller als hier antwortet die API unter Last nie – das ist der beste Fall.",
        "flat": "Danach steigt die Leistung nicht mehr: Zusätzliche Anfragen warten nur länger.",
        "more_but_slow": "Mehr Anfragen gehen zwar noch durch – aber nur, weil jede länger wartet als gewünscht.",
        "soak_stable": "Die API blieb über die ganze Zeit gleich schnell.",
        "control_intro": " Die Kontrollmessung ganz am Ende – wieder eine Anfrage allein: ",
        "pointer_slow": ("Die API braucht schon ohne Last lange für die erste Antwort",
                         "{t}, bevor überhaupt etwas kommt. Meist steckt die Zeit in Datenbankabfragen oder "
                         "Aufrufen weiterer Dienste – dort zuerst messen."),
        "pointer_few": ("Schon wenige gleichzeitige Anfragen sind zu viel",
                        "Bevor mehr Leistung gekauft wird, zuerst die Antwortzeit ohne Last senken – sie ist die "
                        "Untergrenze für alles Weitere."),
        "pointer_gap": ("Zwischen {a} und {b} gleichzeitig wird es eng",
                        "Vor Lastspitzen einplanen: mehr Instanzen, ein Cache für häufige Antworten oder eine "
                        "Begrenzung pro Aufrufer (Rate-Limit), damit einzelne nicht alle ausbremsen."),
        "pointer_target": ("Die erwartete Menge wird nicht erreicht",
                           "Es gehen ≈ {users} Anfragen pro Minute flüssig durch, erwartet werden {target}. Die Lücke "
                           "lässt sich nur mit schnelleren Antworten oder mehr Leistung schließen."),
        "pointer_ok": ("Kein dringender Handlungsbedarf",
                       "Die API erreicht alle gesetzten Ziele. Sinnvoll ist, den Test nach größeren Änderungen zu "
                       "wiederholen und die Läufe zu vergleichen."),
        "assumptions": ["• Getestet wurde genau eine Anfrage ({method} {path}). Andere Endpunkte können schneller "
                        "oder langsamer sein.",
                        "• Als „rechtzeitig“ gilt eine Antwort, wenn fast alle (95 %) nach höchstens {slo} da sind.",
                        "• Die simulierten Clients halten ihre Verbindungen offen (Keep-Alive), wie Programme es tun.",
                        "• Jede Anfrage wurde wirklich ausgeführt – bei schreibenden Methoden hat der Test also Daten "
                        "verändert."],
        "not_measured": ["• Abläufe über mehrere Anfragen: Anmelden, dann Abfragen, dann Speichern.",
                         "• Die Verarbeitung der Antwort beim Aufrufer.",
                         "• Dienste, die die API im Hintergrund selbst aufruft – nur ihre Gesamtwirkung ist enthalten.",
                         "• Die Netzverbindung der echten Aufrufer. Gemessen wurde vom Messrechner aus."],
        "pdf_kicker": "LASTTEST HTTP-API · KURZBERICHT",
        "pdf_foot": "Anfragen pro Minute = höchste zufällig verteilte Last im Ziel – eine Messung bei dieser "
                    "Anfrage ({method} {path}), keine Garantie für andere Endpunkte.",
        "pdf_foot2": "Nicht gemessen: Abläufe über mehrere Anfragen, die Verarbeitung beim Aufrufer.",
        "compare_hint": "Liegt die neue Linie durchgehend unter der alten, hat die Änderung geholfen – auch unter "
                        "Last, nicht nur im Leerlauf.",
        "compare_more": "Eine höhere Linie bedeutet: Dieselbe API schafft mehr Anfragen.",
        "little": "Kapazität = höchste Rate der offenen Last (Echter Andrang), bei der Antwortzeit p95 und "
                  "Fehlerquote im Ziel bleiben, in Anfragen pro Minute; ohne offene Last der Durchsatz der höchsten "
                  "Stufe, die das Ziel erreicht.",
    },
}


def kind_of(summary):
    kind = (summary.get("config") or {}).get("kind")
    return kind if kind in TEXTS else "web"


def texts(summary):
    return TEXTS[kind_of(summary)]


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


def signed(p):
    """+12 %, −50 %, ±0 % – mit echtem Minuszeichen."""
    if p is None:
        return "–"
    r = round(p)
    return f"{'+' if r > 0 else '−' if r < 0 else '±'}{abs(r)} %"


def endpoint(cfg):
    """„GET /v1/items“ für API-Läufe."""
    from urllib.parse import urlparse
    return cfg.get("method", "GET"), urlparse(cfg.get("base_url", "")).path or "/"


def control_note(summary):
    """Kontrollmessung in Worten. Unterschiede unter 5 % oder 0,05 s sind Messrauschen."""
    ctl, base = summary.get("control") or {}, summary.get("baseline") or {}
    d = ctl.get("ttft_diff_pct")
    if d is None:
        return None
    a, b = base.get("e2e_p50"), (ctl.get("s") or {}).get("e2e_p50")
    same = abs(d) < 5 or (a is not None and b is not None and abs(b - a) < 0.05)
    t = texts(summary)["time"]
    return (GOOD, "so schnell wie am Anfang") if same else (
        GOOD if d <= 25 else WARN, f"{signed(d)} {t} gegenüber dem Anfang")


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
        "api": kind_of(summary) == "api", "flow": kind_of(summary) == "flow", "t": texts(summary),
    }


def headline_cards(summary):
    """Die vier Zahlen für die Entscheidung: (Wert, Beschriftung, Erläuterung, Farbe)."""
    f = facts(summary)
    t, api = f["t"], f["api"]
    users, target, base, rec, top = f["users"], f["target"], f["base"], f["rec"], f["top"]
    cards = []
    if f["steps"] or f["stages"]:  # ohne Lasttest gibt es keine Kapazität
        cards.append((f"≈ {approx(users)}" if users else "0", t["unit_label"],
                      f"erwartet: {n0(target)}" if target
                      else ("bei zufällig verteilten Anfragen" if api else f"bei {n0(f['think'])} s Pause {t['pause']}"),
                      (GOOD if not target or users >= target else WARN if users >= 0.7 * target else BAD)
                      if users else BAD))
    if base:
        load = base.get("e2e_p50")
        cards.append((secs(load), t["time_alone"], time_feel(load),
                      GOOD if load is not None and load <= f["slo"] else WARN))
    if f["steps"]:
        cards.append((str(rec["concurrency"]) if rec else "0", "gleichzeitig ohne Frust",
                      f"fast alle {t['ready']} dann nach höchstens {secs(f['slo'])}" if rec
                      else "schon die kleinste Stufe ist zu langsam",
                      GOOD if rec else BAD))
    if top and top.get("req_s"):
        cards.append((n0(top["req_s"] * 60), "Höchstleistung pro Minute" if api else t["per_min_long"],
                      "mehr Anfragen gehen überhaupt nicht durch – egal, wie langsam" if api
                      else "mehr schafft der Server insgesamt nicht", INK))
    return cards


def result_rows(summary):
    """Alle Ergebnisse als Ampel-Zeilen: (Farbe, Bereich, Ergebnis)."""
    f = facts(summary)
    t, api = f["t"], f["api"]
    slo, base, steps, rec = f["slo"], f["base"], f["steps"], f["rec"]
    rows = []
    if base:
        load, first = base.get("e2e_p50"), base.get("ttft_p50")
        rows.append((GOOD if load is not None and load <= slo else WARN, t["time_alone"],
                     f"{secs(load)} {t['done']} – {time_feel(load)}"))
        rows.append((INFO if first is None else GOOD if first <= GOOD_TTFB else WARN if first <= SLOW_TTFB else BAD,
                     "Erste Antwort des Servers",
                     f"{secs(first)} – " + ("zügig" if first is not None and first <= GOOD_TTFB else
                                           "der Server lässt sich Zeit, bevor überhaupt etwas kommt")))
    if steps:
        rows.append((GOOD if rec else BAD, "Gleichzeitig flüssig",
                     t["zaeh"].format(c=rec["concurrency"]) if rec else t["zaeh_none"]))
        if f["brk"]:
            rows.append((BAD, "Belastungsgrenze", f"ab {f['brk']['concurrency']} gleichzeitig: {f['brk']['reason']}"))
        else:
            rows.append((GOOD, "Belastungsgrenze",
                         f"bis {steps[-1]['concurrency']} gleichzeitig keine Fehler und kein Abbruch"))
    if f["stages"]:
        ok = f["cap"].get("rate_ok")
        rows.append((GOOD if ok else BAD, "Echter Andrang",
                     (f"bis {per_min(ok)} {t['per_min']} flüssig" if ok else "schon die kleinste Menge ist zu viel")
                     + (f", ab {per_min(f['rbrk']['rate'])}/min wächst die Schlange" if f["rbrk"] else "")))
    spike = f["spike"]
    if spike:
        burst = spike["burst"]
        if spike.get("crashed"):
            rows.append((BAD, "Großer Ansturm", f"{spike['size']} auf einmal – danach war {t['subject']} nicht mehr erreichbar"))
        elif burst["errors"]:
            rows.append((WARN, "Großer Ansturm", f"{spike['size']} auf einmal – {burst['errors']} {t['fail']}"))
        elif spike.get("recovered") is False:
            rows.append((WARN, "Großer Ansturm", f"{spike['size']} auf einmal – alle bedient, danach aber langsamer als vorher"))
        else:
            rows.append((GOOD, "Großer Ansturm",
                         f"{spike['size']} auf einmal – alle bedient, längste {t['time']} {secs(burst.get('e2e_max'))}"))
    soak = f["soak"]
    if soak:
        slower = (soak.get("degradation") or {}).get("ttft_change_pct")
        failed = soak["total"]["error_rate"] > 0
        rows.append((BAD if failed else WARN if slower is not None and slower > 25 else GOOD, "Ausdauer",
                     f"nach {mins(soak['minutes'])} "
                     + (f"{fmt(soak['total']['error_rate'] * 100, 1)} % Fehler" if failed
                        else "unverändert schnell" if slower is None or abs(slower) < 5
                        else f"{signed(slower)} {t['time']}")))
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
    if total and not api and not f["flow"]:
        rows.append((GOOD if total <= LIGHT_PAGE else WARN if total <= HEAVY_PAGE else BAD, "Gewicht der Seite",
                     f"{size(total)} mit {n0(f['pre'].get('assets', 0))} Dateien"
                     + ("" if total <= LIGHT_PAGE else " – schwer; das kostet bei jedem Besuch Zeit")))
    return rows


def pointers(summary):
    """Mögliche Ansatzpunkte – abgeleitet aus dem, was gemessen wurde. Der Test zeigt,
    wo es hakt, nicht warum; deshalb vorsichtig formuliert."""
    f = facts(summary)
    t, api = f["t"], f["api"]
    base, pre, rec, steps = f["base"], f["pre"], f["rec"], f["steps"]
    out = []
    if base and base.get("ttft_p50") is not None and base["ttft_p50"] > GOOD_TTFB:
        head, body = t["pointer_slow"]
        out.append((head, body.format(t=secs(base["ttft_p50"]))))
    if not api and not f["flow"] and pre.get("total_bytes") and pre["total_bytes"] > LIGHT_PAGE:
        biggest = (pre.get("files") or [{}])[0]
        out.append(("Die Seite ist schwer",
                    f"{size(pre['total_bytes'])} pro Besuch"
                    + (f"; allein {biggest['path']} wiegt {size(biggest['bytes'])}" if biggest.get("path") else "")
                    + ". Kleinere Bilder und weniger Skripte entlasten Server und Besucher zugleich."))
    if steps and not rec:
        out.append(t["pointer_few"])
    elif rec and steps and rec is not steps[-1]:
        nxt = steps[steps.index(rec) + 1]
        head, body = t["pointer_gap"]
        out.append((head.format(a=rec["concurrency"], b=nxt["concurrency"]), body))
    if f["target"] and f["users"] and f["users"] < f["target"]:
        head, body = t["pointer_target"]
        out.append((head, body.format(users=approx(f["users"]), target=n0(f["target"]))))
    if f["spike"] and (f["spike"].get("crashed") or f["spike"]["burst"]["errors"]):
        out.append(("Ein plötzlicher Ansturm führt zu Fehlern",
                    "Prüfen, ob der Server Anfragen in eine Warteschlange stellen kann, statt sie abzuweisen."))
    if not out:
        out.append(t["pointer_ok"])
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


def _flow_slides(d, summary, f, outdir):
    """Ablauf: Schritte und aufgezeichnete Anfragen, dazu die Bildschirmfotos des Browsers."""
    cfg, pre, slo = f["cfg"], f["pre"], f["slo"]
    sl = d.slide()
    title(sl, "So haben wir getestet", "Einmal im echten Browser aufgezeichnet, dann hunderte Male ohne Browser abgespielt")
    lines = [ln.strip() for ln in (cfg.get("steps_text") or "").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    text(sl, 0.6, 1.8, 5.6, 0.35, "Die Schritte", size=14, bold=True, color=S1)
    rows = []
    for ln in lines[:14]:
        measure = "messen" in ln.lower() and ("ab hier" in ln.lower() or ln.lower().strip("─-—= ") == "messen")
        rows.append([("▶ ab hier wird gemessen" if measure else _short(ln, 58), S1 if measure else None)])
    if len(lines) > 14:
        rows.append([(f"… und {len(lines) - 14} weitere Schritte", MUTED)])
    for i, (row,) in enumerate(rows):
        txt, col = row
        text(sl, 0.6, 2.2 + i * 0.3, 5.6, 0.3, txt, size=11, color=col or INK2, font="Consolas" if not col else "Calibri",
             bold=bool(col))
    reqs = pre.get("requests") or []
    text(sl, 6.6, 1.8, 6.1, 0.35, "Was die Seite im Messbereich an den Server schickt", size=14, bold=True, color=S1)
    table_rows = [["Anfrage", "Status", "gestreamt", "veränderlich"]]
    for i, q in enumerate(reqs[:8]):
        path_ = re.sub(r"\{\{(\w+)\}\}", r"{\1}", q["path"])           # {{v1}} → {v1}
        table_rows.append([(f"{q['method']} {_short(path_, 40)}", S1 if i == pre.get("main") else None),
                           str(q["status"]), "ja" if q["stream"] else "–", ", ".join(q["dynamic"]) or "–"])
    table(sl, 6.6, 2.25, 6.15, table_rows, col_w=[3.55, 0.7, 0.9, 1.0], font=10)
    y_after = 2.35 + 0.34 * len(table_rows)
    text(sl, 6.6, y_after, 6.15, 1.4, [
        "Blau: die Hauptanfrage – an ihr wird „erstes Wort“ gemessen.",
        "Veränderliche Werte (z. B. eine Chat-ID) kommen aus einer früheren Antwort und werden bei jeder "
        "Wiederholung frisch geholt." if any(q["dynamic"] for q in reqs) else
        "Keine veränderlichen Werte: Jede Wiederholung schickt genau dieselben Anfragen.",
    ], size=11.5, color=INK2, space_after=5)
    footer(sl, "Zugangsdaten stehen nur in Platzhaltern und wurden nicht gespeichert; die Sitzung lebt nur im "
               f"Arbeitsspeicher des Tests. Ziel: Antwort nach höchstens {secs(slo)}.")
    notes(sl, "Aufzeichnung mit Chromium (Playwright), Netzwerkmitschnitt ab „messen ab hier“ (XHR/fetch/Dokument/"
              "EventSource). Abspielen mit aiohttp, Keep-Alive, Cookies aus der Aufzeichnung. Hauptanfrage = gestreamte "
              "Antwort, sonst die längste. Veränderliche Werte: Tokens in Adresse/Body/X-Kopfzeilen, die als Blatt in "
              "einer früheren JSON-Antwort vorkommen.")

    shots = [s for s in (pre.get("steps") or []) if s.get("screenshot") and outdir
             and os.path.isfile(os.path.join(outdir, s["screenshot"]))]
    if shots:
        sl = d.slide()
        title(sl, "Was der Browser gesehen hat", "Bildschirmfotos aus der Aufzeichnung – zur Kontrolle, ob die Schritte stimmen")
        # Interessant sind der Anfang, der Stand kurz vor „messen“ und alles im Messbereich
        m = next((i for i, s in enumerate(shots) if s["text"].startswith("messen")), len(shots))
        before = {s["line"]: s for s in shots[:1] + shots[max(0, m - 1):m]}
        pick = list(before.values()) + shots[m + 1:]
        if len(pick) > 6:
            pick = list(before.values())[-1:] + shots[m + 1:][-5:]
        cols = 3
        cw, ch = (W - 1.2 - 0.3 * (cols - 1)) / cols, 2.35
        for i, s in enumerate(pick[:6]):
            x, y = 0.6 + (i % cols) * (cw + 0.3), 1.7 + (i // cols) * (ch + 0.45)
            try:
                sl.shapes.add_picture(os.path.join(outdir, s["screenshot"]), Inches(x), Inches(y), width=Inches(cw),
                                      height=Inches(ch))
            except Exception:
                rect(sl, x, y, cw, ch, PANEL)
            text(sl, x, y + ch + 0.05, cw, 0.35, f"Zeile {s['line']}: {_short(s['text'], 48)}", size=10.5, color=INK2)
        notes(sl, "Je ein Foto nach jedem Schritt; hier der Anfang, der Stand vor „messen“ und der Messbereich. Alle Fotos liegen als "
                  "schritt_NN.png im Ergebnisordner.")


def _method_slide(d, summary, f, outdir=None):
    """Folie „So haben wir getestet“ – je Testart anders."""
    cfg, pre, slo = f["cfg"], f["pre"], f["slo"]
    if kind_of(summary) == "flow":
        _flow_slides(d, summary, f, outdir)
        return
    sl = d.slide()
    if f["api"]:
        method, path = endpoint(cfg)
        title(sl, "So haben wir getestet", "Jede simulierte Anfrage ist genau die Anfrage aus dem Formular")
        _bullets(sl, 0.6, 1.85, 6.4, [
            ("Anfrage schicken", f"{method} {path}. Die Zeit, bis der Server die ersten Daten schickt, heißt "
                                 "„erste Antwort“."),
            ("Antwort abwarten", "Erst wenn die Antwort vollständig da ist, zählt die Anfrage als erledigt. Diese "
                                 f"„Antwortzeit“ ist das, was Aufrufer spüren. Ziel: höchstens {secs(slo)}."),
            ("Antwort prüfen", f"Erwartet wird Status {cfg.get('expect_status', '2xx')}. Jede andere Antwort zählt "
                               "als Fehler – auch wenn sie schnell kam."),
            ("Immer mehr Anfragen", "Erst eine allein, dann stufenweise mehr gleichzeitig, dann zufällig "
                                    "eintreffend wie im Alltag, ein plötzlicher Ansturm und zum Schluss Dauerlast."),
        ])
        rect(sl, 7.5, 1.85, 5.25, 2.6, PANEL)
        text(sl, 7.8, 2.05, 4.65, 0.35, "Die getestete Anfrage", size=14, bold=True, color=S1)
        names = cfg.get("header_names") or []
        body_bytes = cfg.get("body_bytes") or 0
        text(sl, 7.8, 2.5, 4.65, 1.9, [
            [("Methode: ", {"bold": True}), method],
            [("Adresse: ", {"bold": True}), _short(cfg.get("base_url", ""), 60)],
            [("Kopfzeilen: ", {"bold": True}), ", ".join(names) if names else "keine zusätzlichen"],
            [("Body: ", {"bold": True}), f"{size(body_bytes)}" if body_bytes else "keiner"],
            [("Antwort ohne Last: ", {"bold": True}), f"Status {pre.get('status', '–')}, {size(pre.get('bytes'))}"],
        ], size=12, color=INK2, space_after=4)
        footer(sl, "Die Werte der Kopfzeilen und der Body wurden nicht gespeichert – sie enthalten oft Zugangsdaten.")
        notes(sl, f"HTTP {method} auf die Adresse mit den angegebenen Kopfzeilen und dem Body; Weiterleitungen werden "
                  "nicht verfolgt. Verbindungen werden wiederverwendet (Keep-Alive). Erste Antwort = TTFB, "
                  "Antwortzeit = bis zum letzten Byte. Status wird gegen die Erwartung geprüft.")
        return
    n_files = pre.get("assets", 0)
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


def build_report(summary, path):
    d = Deck()
    f = facts(summary)
    t, api = f["t"], f["api"]
    cfg, slo, think = f["cfg"], f["slo"], f["think"]
    base, pre, steps, rec, top = f["base"], f["pre"], f["steps"], f["rec"], f["top"]
    stages, spike, soak, users, vd = f["stages"], f["spike"], f["soak"], f["users"], f["verdict"]
    url = cfg.get("base_url", "")
    n_files = pre.get("assets", 0)
    method, path_ = endpoint(cfg)
    fill = {"think": n0(think), "slo": secs(slo), "method": method, "path": path_}

    # ═══ Titel ═══
    sl = d.slide(dark=True)
    text(sl, 0.8, 1.55, 11.5, 0.45, "BELASTUNGSTEST", size=15, color="94A3B8", bold=True)
    text(sl, 0.8, 2.0, 11.8, 1.0, t["title"], size=40, color="FFFFFF", bold=True, font="Cambria")
    text(sl, 0.8, 3.05, 11.8, 0.6, f"{method} {url}" if api else url, size=24, color="CBD5E1")
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
    footer(sl, t["capacity_note"].format(**fill))
    notes(sl, "Urteil: grün, wenn die Kapazität zur erwarteten Last passt und Ansturm sowie Dauerlast sauber "
              "überstanden wurden; gelb bei knapper Kapazität, Fehlern im Ansturm oder langsamer werdenden "
              f"Antworten; rot, wenn die Kapazität deutlich nicht reicht oder {t['subject']} ausfiel. "
              f"Ziel (SLO): {t['time']} p95 ≤ {fmt(slo, 2)} s, keine Fehler.")

    # ═══ So haben wir getestet ═══
    _method_slide(d, summary, f, os.path.dirname(os.path.abspath(path)))

    # ═══ Einer allein ═══
    if base:
        sl = d.slide()
        title(sl, "Einer allein", t["alone_sub"])
        first, load = base.get("ttft_p50"), base.get("e2e_p50")
        bw = (W - 1.2 - 0.5) / 3
        stat(sl, 0.6, 1.9, bw, 2.2, secs(first), "Erste Antwort des Servers",
             "so lange braucht der Server, bevor überhaupt etwas kommt",
             color=GOOD if first is not None and first <= GOOD_TTFB else WARN if first is not None and first <= SLOW_TTFB else BAD,
             vsize=36)
        stat(sl, 0.6 + bw + 0.25, 1.9, bw, 2.2, secs(load), t["time_long"], time_feel(load),
             color=GOOD if load is not None and load <= slo else WARN, vsize=36)
        if api:
            stat(sl, 0.6 + 2 * (bw + 0.25), 1.9, bw, 2.2, size(pre.get("bytes")), "Größe einer Antwort",
                 f"Status {pre.get('status', '–')} bei {method} {_short(path_, 28)}", vsize=36)
        elif kind_of(summary) == "flow":
            reqs = pre.get("requests") or []
            stat(sl, 0.6 + 2 * (bw + 0.25), 1.9, bw, 2.2, str(len(reqs)), "Anfragen je Durchlauf",
                 "so viele Anfragen schickt die Seite im Messbereich an den Server", vsize=36)
        else:
            stat(sl, 0.6 + 2 * (bw + 0.25), 1.9, bw, 2.2, size(pre.get("total_bytes") or pre.get("bytes")),
                 "Gewicht eines Besuchs", f"die Seite und {n0(n_files)} Dateien", vsize=36)
        rect(sl, 0.6, 4.45, W - 1.2, 2.2, PANEL)
        text(sl, 0.9, 4.65, W - 1.8, 0.35, "Was das bedeutet", size=14, bold=True, color=S1)
        text(sl, 0.9, 5.05, W - 1.8, 1.5, [
            t["best_case"],
            f"Richtwerte: Eine erste Antwort unter {fmt(GOOD_TTFB, 1)} s gilt als zügig, über {fmt(SLOW_TTFB, 1)} s als träge. "
            f"Bei der {t['time']} haben wir uns höchstens {secs(slo)} vorgenommen.",
            (f"Gemessen: Die Hälfte der {t['units']} war nach {secs(load)} fertig, fast alle (95 %) nach "
             f"{secs(base.get('e2e_p95'))}."),
        ], size=13, color=INK, space_after=6)
        notes(sl, f"Baseline: {base['n']} {t['units']} nacheinander. TTFB p50 {fmt(first, 3)} s / p95 "
                  f"{fmt(base.get('ttft_p95'), 3)} s; {t['time']} p50 {fmt(load, 3)} s / p95 "
                  f"{fmt(base.get('e2e_p95'), 3)} s; Fehler {base['errors']}.")

    # ═══ Immer mehr gleichzeitig ═══
    if steps:
        cats = [s["concurrency"] for s in steps]
        sl = d.slide()
        title(sl, "Immer mehr gleichzeitig", t["ramp_sub"])
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, cats,
                   [("normal (die Hälfte ist schneller)", [s.get("e2e_p50") for s in steps]),
                    ("fast alle (95 % sind schneller)", [s.get("e2e_p95") for s in steps]),
                    (f"Ziel: {secs(slo)}", [slo] * len(steps))],
                   y_title=t["y_axis"], x_title=t["x_axis"],
                   colors=(S1, S2, MUTED), dashed=(2,), number_format="0.00")
        if rec:
            meaning = (f"Bis {rec['concurrency']} gleichzeitig bleibt {t['subject']} für fast alle unter dem Ziel. "
                       + (f"Bei {steps[steps.index(rec) + 1]['concurrency']} wird es zu langsam."
                          if rec is not steps[-1] else "Die Grenze liegt oberhalb der getesteten Stufen."))
        else:
            meaning = f"Schon bei der kleinsten Stufe liegt die {t['time']} über dem Ziel."
        if f["brk"]:
            meaning += f" Abbruch bei {f['brk']['concurrency']}: {f['brk']['reason']}."
        explain(sl, f"Nach rechts kommen immer mehr {t['units']} gleichzeitig. Die blaue Linie zeigt, wie lange "
                    "eine typische wartet, die orange, wie lange fast alle warten. Solange Orange "
                    "unter der gestrichelten Linie bleibt, ist alles gut." if api else
                    f"Nach rechts kommen immer mehr {t['units']} gleichzeitig. Die blaue Linie zeigt, wie lange "
                    f"ein typischer {t['one']} wartet, die orange, wie lange fast alle warten. Solange Orange "
                    "unter der gestrichelten Linie bleibt, ist alles gut.", meaning)
        footer(sl, t["gleichzeitig_note"])
        notes(sl, f"Ramp mit fester Parallelität, je Stufe {n0(cfg.get('level_seconds', 0))} s im eingeschwungenen "
                  f"Zustand. Linien: {t['time']} p50 und p95. Ziel erreicht = p95 ≤ SLO und keine Fehler.")

        # ═══ Gesamtleistung ═══
        sl = d.slide()
        title(sl, "Wie viel schafft der Server insgesamt?", f"{t['throughput']} für alle zusammen")
        bar_chart(sl, 0.6, 1.7, 6.2, 5.0, cats, [s.get("req_s") or 0 for s in steps],
                  y_title=t["throughput"], x_title=t["x_axis"], color=S1, number_format="0.0")
        rows = [["gleichzeitig", t["throughput_short"], f"{t['time']} normal", "fast alle", "Fehler", "Ziel"]]
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
                f"Höchstleistung: {fmt(top.get('req_s'), 1)} {t['throughput'].lower()} – das sind "
                f"{n0((top.get('req_s') or 0) * 60)} {t['per_min_long']}.",
                t["flat"] if flat else
                "Die Leistung stieg bis zur letzten Stufe – der Server war noch nicht am Anschlag." if last_ok else
                t["more_but_slow"]],
                size=12.5, color=INK2, space_after=6)
        notes(sl, f"{t['throughput_short']} = abgeschlossene {t['units']} pro Sekunde im Messfenster.")

    # ═══ Echter Andrang ═══
    if stages:
        sl = d.slide()
        title(sl, "Echter Andrang", t["rate_sub"])
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, [per_min(s["rate"]) for s in stages],
                   [("normal (die Hälfte ist schneller)", [s.get("e2e_p50") for s in stages]),
                    ("fast alle (95 % sind schneller)", [s.get("e2e_p95") for s in stages]),
                    (f"Ziel: {secs(slo)}", [slo] * len(stages))],
                   y_title=t["y_axis"], x_title=t["rate_axis"],
                   colors=(S1, S2, MUTED), dashed=(2,), number_format="0.00")
        ok = f["cap"].get("rate_ok")
        meaning = (f"Bis {per_min(ok)} {t['per_min_long']} läuft es flüssig." if ok
                   else "Schon die kleinste getestete Menge war zu viel.")
        if f["rbrk"]:
            meaning += f" Ab {per_min(f['rbrk']['rate'])} pro Minute: {f['rbrk']['reason']}."
        if users and t["rate_meaning_users"]:
            meaning += t["rate_meaning_users"].format(users=approx(users), think=n0(think))
        explain(sl, f"Hier kommen die {t['units']} nicht im Gleichschritt, sondern zufällig wie im Alltag. So zeigt "
                    "sich, ob sich eine Warteschlange aufbaut. Nach rechts wird der Andrang größer.", meaning)
        notes(sl, f"Offene Last mit Poisson-Ankünften. Überlastet = {t['time']} der letzten {t['units']} mehr als "
                  "doppelt so hoch wie die der ersten und über dem Ziel, oder Fehlerquote über "
                  f"{fmt(DEFAULTS['max_error_rate'] * 100, 0)} %.")

    # ═══ Großer Ansturm ═══
    if spike:
        sl = d.slide()
        title(sl, "Großer Ansturm", t["spike_sub"].format(n=spike["size"]))
        burst, bw = spike["burst"], (W - 1.2 - 0.5) / 3
        stat(sl, 0.6, 1.9, bw, 2.2, f"{burst['ok']} von {burst['n']}", "wurden bedient",
             t["served"] if not burst["errors"] else f"{burst['errors']} {t['fail']}",
             color=GOOD if not burst["errors"] else BAD, vsize=36)
        stat(sl, 0.6 + bw + 0.25, 1.9, bw, 2.2, secs(burst.get("e2e_max")), f"längste {t['time']}",
             time_feel(burst.get("e2e_max")), vsize=36)
        crashed, back = spike.get("crashed"), spike.get("recovered")
        stat(sl, 0.6 + 2 * (bw + 0.25), 1.9, bw, 2.2,
             "ausgefallen" if crashed else "ja" if back else "nein" if back is False else "–",
             "danach wieder normal?",
             f"{t['subject']} war nicht mehr erreichbar" if crashed else
             "kurz darauf so schnell wie vor dem Ansturm" if back else "blieb langsamer als vorher",
             color=BAD if crashed else GOOD if back else WARN, vsize=36)
        rect(sl, 0.6, 4.45, W - 1.2, 1.7, PANEL)
        text(sl, 0.9, 4.65, W - 1.8, 0.35, "Was das bedeutet", size=14, bold=True, color=S1)
        text(sl, 0.9, 5.05, W - 1.8, 1.0,
             "Ein Ansturm ist härter als gleichmäßige Last: Alle kommen im selben Moment, der Server hat keine "
             "Zeit, sich einzuschwingen. Wichtig ist weniger die Wartezeit im Ansturm als die Frage, ob jemand "
             f"abgewiesen wurde und ob sich {t['subject']} danach erholt.", size=13, color=INK)
        notes(sl, f"Burst: {burst['n']} {t['units']} gleichzeitig gestartet. {t['time']} p50 {fmt(burst.get('e2e_p50'), 2)} s, "
                  f"p95 {fmt(burst.get('e2e_p95'), 2)} s. Erholung: 3 {t['units']} nacheinander, verglichen mit der "
                  f"Baseline (höchstens 1,5-fache {t['time']}).")

    # ═══ Ausdauer ═══
    if soak:
        sl = d.slide()
        title(sl, "Ausdauer", f"{mins(soak['minutes'])} gleichmäßige Last mit {soak['concurrency']} gleichzeitig")
        buckets = [b for b in soak.get("buckets") or [] if b.get("s")]
        deg = soak.get("degradation") or {}
        slower = deg.get("ttft_change_pct")
        if len(buckets) >= 2:
            line_chart(sl, 0.6, 1.7, 8.1, 5.0, [fmt(b["t_min"], 1) for b in buckets],
                       [(f"{t['time']} (normal)", [b["s"].get("e2e_p50") for b in buckets]),
                        (f"Ziel: {secs(slo)}", [slo] * len(buckets))],
                       y_title=t["y_axis"], x_title="Minuten seit Beginn",
                       colors=(S1, MUTED), dashed=(1,), number_format="0.00")
        else:
            stat(sl, 0.6, 1.9, 8.1, 2.2, secs(soak["total"].get("e2e_p50")), f"{t['time']} unter Dauerlast",
                 time_feel(soak["total"].get("e2e_p50")), vsize=36)
        meaning = (t["soak_stable"] if slower is None or abs(slower) < 5
                   else f"Am Ende war die {t['time']} {signed(slower)} gegenüber dem Anfang."
                   + (" Das deutet auf ein Problem hin, das mit der Zeit wächst." if slower > 25 else ""))
        if soak["total"]["errors"]:
            meaning += f" Dabei gab es {soak['total']['errors']} Fehler."
        ctl_note = control_note(summary)
        if ctl_note:
            meaning += t["control_intro"] + ctl_note[1] + "."
        explain(sl, f"Die Linie zeigt die {t['time']} über die Dauer des Tests. Sie soll waagerecht bleiben. "
                    "Steigt sie an, geht dem Server mit der Zeit etwas aus – zum Beispiel Speicher oder "
                    "Datenbankverbindungen.", meaning)
        notes(sl, f"Soak: {soak['total']['n']} {t['units']}, Fehlerquote {fmt(soak['total']['error_rate'] * 100, 2)} %. "
                  "Vergleich erstes gegen letztes Drittel: Durchsatz "
                  f"{signed(deg.get('tps_change_pct'))}, {t['time']} p50 {signed(slower)}.")

    # ═══ Alles auf einen Blick ═══
    sl = d.slide()
    title(sl, "Alles auf einen Blick")
    rect(sl, 0.6, 1.5, 3.7, 5.2, DARK_BG)
    text(sl, 0.9, 1.8, 3.1, 0.4, "SCHAFFT" if api else "REICHT FÜR", size=13, bold=True, color="94A3B8")
    text(sl, 0.9, 2.3, 3.1, 1.3, f"≈ {approx(users)}" if users else "–", size=60, bold=True, color="FFFFFF",
         font="Cambria")
    text(sl, 0.9, 3.75, 3.1, 0.8, t["capacity_label"], size=16, color="CBD5E1")
    text(sl, 0.9, 4.9, 3.1, 1.6,
         (f"Erwartet: {n0(f['target'])}. " if f["target"] else "") + t["capacity_sub"].format(**fill),
         size=12.5, color="94A3B8")
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
    text(sl, 0.9, 2.4, 5.35, 4.0, [a.format(**fill) for a in t["assumptions"]], size=12.5, color=INK, space_after=7)
    rect(sl, 6.8, 1.7, 5.95, 3.9, CARD)
    text(sl, 7.1, 1.9, 5.35, 0.4, "Nicht gemessen", size=15, bold=True, color=S2)
    text(sl, 7.1, 2.4, 5.35, 4.0, t["not_measured"], size=12.5, color=INK, space_after=7)
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
    notes(sl, t["little"])

    d.save(path)
    return path


# ════════════════════════════════════════════════════════════════════════════
#  PDF – eine A4-Seite
# ════════════════════════════════════════════════════════════════════════════

def build_pdf(summary, path):
    from reportlab.lib.colors import HexColor

    from report_pdf import PH, PW, M, Page, chart

    pg = Page(path)
    c = pg.c
    f = facts(summary)
    t, api = f["t"], f["api"]
    cfg, slo, vd = f["cfg"], f["slo"], f["verdict"]
    steps, stages = f["steps"], f["stages"]
    method, path_ = endpoint(cfg)
    cw = PW - 2 * M
    y = PH - M

    pg.text(M, y - 8, t["pdf_kicker"], 7.5, True, MUTED)
    pg.text(M, y - 30, t["title"], 19, True)
    started = when(summary)
    first_line = f"{method} {cfg.get('base_url', '')}" if api else cfg.get("base_url", "")
    pg.text(M, y - 45, " · ".join(x for x in (first_line, f"getestet am {started}" if started else "") if x),
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
        x_short = t["unit_label"]
        if stages:
            chart(pg, M, y - ch_h, half, ch_h, f"{t['time']}, wenn die {t['units']} zufällig kommen",
                  [("normal", S1, [(s["rate"] * 60, s.get("e2e_p50")) for s in stages]),
                   ("fast alle", S2, [(s["rate"] * 60, s.get("e2e_p95")) for s in stages])],
                  t["rate_axis"], t["y_axis"], slo, f"Ziel ≤ {fmt(slo, 1)} s", 1)
        else:
            chart(pg, M, y - ch_h, half, ch_h, f"{t['time']} bei zunehmender Last",
                  [("normal", S1, [(s["concurrency"], s.get("e2e_p50")) for s in steps]),
                   ("fast alle", S2, [(s["concurrency"], s.get("e2e_p95")) for s in steps])],
                  x_short, t["y_axis"], slo, f"Ziel ≤ {fmt(slo, 1)} s", 1)
        chart(pg, M + half + 14, y - ch_h, half, ch_h, "Gesamtleistung",
              [("alle zusammen", S1, [(s["concurrency"], s.get("req_s")) for s in steps])],
              x_short, t["throughput"], dec=1)
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
    files = f" und {n0(pre['assets'])} Dateien derselben Website" if pre.get("assets") else ""
    foot = [t["pdf_foot"].format(think=n0(f["think"]), files=files, method=method, path=path_), t["pdf_foot2"]]
    c.setStrokeColor(HexColor("#E5E7EB"))
    c.line(M, foot_top - 4, M + cw, foot_top - 4)
    yy = foot_top - 8
    for t_ in foot:
        yy = pg.para(M, yy, cw, t_, 6.8, color=MUTED, max_lines=2) - 1
    pg.text(M + cw, M - 12, "Erstellt mit LAST · Details in der PowerPoint", 6.5, color=MUTED, align="right")
    c.setTitle(("Lasttest HTTP-API" if api else "Lasttest Website") + " – Kurzbericht")
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
    t, api = f["t"], f["api"]
    base, rec, top = f["base"] or {}, f["rec"], f["top"] or {}
    peak = (top.get("req_s") or 0) * 60 or None
    figs = [
        (t["unit_label"], f["users"], f"≈ {approx(f['users'])}" if f["users"] else "–", True),
        (t["time_alone"], base.get("e2e_p50"), secs(base.get("e2e_p50")), False),
        ("Erste Antwort des Servers", base.get("ttft_p50"), secs(base.get("ttft_p50")), False),
        ("Gleichzeitig ohne Frust", rec["concurrency"] if rec else None, str(rec["concurrency"]) if rec else "–", True),
        (f"{t['per_min_long']} (Höchstleistung)", peak, n0(peak) if peak else "–", True),
    ]
    if not api:
        figs.append(("Gewicht eines Besuchs", f["pre"].get("total_bytes"), size(f["pre"].get("total_bytes")), False))
    return figs


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
    t = texts(summaries[0])
    figs = [_figures(s) for s in summaries]
    urls = sorted({(s.get("config") or {}).get("base_url", "") for s in summaries})

    sl = d.slide(dark=True)
    text(sl, 0.8, 1.55, 11.5, 0.45, "VERGLEICH", size=15, color="94A3B8", bold=True)
    text(sl, 0.8, 2.0, 11.8, 1.0, t["compare_title"], size=40, color="FFFFFF", bold=True, font="Cambria")
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
    notes(sl, f"{t['unit_label']} wie im Einzelbericht; {t['time']} und erste Antwort jeweils p50 ohne Last; "
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
        title(sl, f"{t['time']} bei zunehmender Last", f"So lange warten fast alle {t['units']} (95 %)")
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, cats, series("e2e_p95") + [(f"Ziel: {secs(slo)}", [slo] * len(cats))],
                   y_title=t["y_axis"], x_title=t["x_axis"],
                   colors=(*colors[:len(labels)], MUTED), dashed=(len(labels),), number_format="0.00")
        explain(sl, "Jede Linie ist ein Lauf. Je tiefer eine Linie liegt, desto schneller war die Antwort. "
                    "Wichtig ist, wie lange sie unter der gestrichelten Ziel-Linie bleibt.", t["compare_hint"])
        notes(sl, f"{t['time']} p95 je Stufe des Stufentests.")

        sl = d.slide()
        title(sl, "Gesamtleistung", f"{t['throughput']} für alle zusammen")
        line_chart(sl, 0.6, 1.7, 8.1, 5.0, cats, series("req_s"), y_title=t["throughput"],
                   x_title=t["x_axis"], colors=colors, number_format="0.0")
        explain(sl, "Je höher eine Linie liegt, desto mehr liefert der Server pro Sekunde aus. "
                    "Wo sie flach wird, ist er am Anschlag.", t["compare_more"])
        notes(sl, f"Durchsatz (abgeschlossene {t['units']} pro Sekunde) je Stufe.")

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
        f"Kleine Unterschiede können Zufall sein – {t['time']}en schwanken von Lauf zu Lauf um einige Prozent.",
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
