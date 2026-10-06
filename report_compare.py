"""
Vergleichsbericht: zwei oder mehr Testläufe nebeneinander (vorher/nachher, Modell A gegen B).
Der erste Lauf ist die Referenz, alle anderen werden daran gemessen.

    python llm_stresstest.py --compare results_A results_B --labels "vorher,nachher"
"""

from pptx.enum.text import MSO_ANCHOR

from llm_stresstest import capacity, economics, fmt, recommended_concurrency, verdict
from report_pptx import (
    BAD,
    DARK_BG,
    GOOD,
    INK,
    INK2,
    MUTED,
    S1,
    S2,
    S3,
    S4,
    Deck,
    W,
    approx,
    dot,
    eur,
    explain,
    footer,
    notes,
    pages,
    per_min,
    rect,
    secs,
    table,
    text,
    title,
    xy_chart,
)

COLORS = (S1, S2, S3, S4, "0E7490", "B45309")

# Einstellungen, deren Unterschied für den Vergleich wichtig ist
CONFIG_KEYS = [("model", "Modell"), ("base_url", "Server"), ("input_len", "Länge der Fragen (Tokens)"),
               ("output_len", "Länge der Antworten (Tokens)"), ("length_mix", "Längen"),
               ("shared_prefix", "Gleicher Einleitungstext (Tokens)"),
               ("disable_thinking", "Nachdenken abgeschaltet"), ("levels", "Stufen"),
               ("level_seconds", "Messzeit pro Stufe (s)"), ("rate_seconds", "Messzeit Echter Andrang (s)"),
               ("context_lengths", "Textlängen"), ("soak_minutes", "Ausdauer (min)"),
               ("slo_ttft", "Ziel Wartezeit (s)"), ("slo_user_tps", "Ziel Tempo (Tokens/s)"),
               ("think_time", "Denkpause (s)"), ("tests", "Tests")]


def _label(s):
    started = (s.get("meta", {}).get("started") or "")
    when = f"{started[8:10]}.{started[5:7]}. {started[11:16]}" if len(started) >= 16 else "?"
    return f"{s.get('config', {}).get('model') or '?'} · {when}"


def figures(s):
    """Kennzahlen eines Laufs: (Name, Wert, Formatierung, höher ist besser?)."""
    steps = sorted((s.get("ramp") or {}).get("steps", []), key=lambda x: x["concurrency"])
    base = s.get("baseline") or {}
    cap_ = capacity(s)
    eco = economics(s) or {}
    pr = s.get("probes") or {}
    rec = recommended_concurrency(s)
    rec_step = next((x for x in steps if x["concurrency"] == rec), None) or {}
    top = max((x["out_tps"] or 0 for x in steps), default=None)
    ctx = s.get("context") or {}
    q = (s.get("quality") or {}).get("overall")
    return [
        ("Aktive Nutzer (geschätzt)", cap_.get("users"), lambda v: "≈ " + approx(v), True),
        ("Fragen gleichzeitig flüssig", rec, lambda v: fmt(v), True),
        ("Gesamtleistung max. (Tokens/s)", top or None, lambda v: fmt(v, 0), True),
        ("Tempo für eine Person (Tokens/s)", base.get("user_tps_p50"), lambda v: fmt(v, 1), True),
        ("Wartezeit ohne Andrang", base.get("ttft_p50"), lambda v: secs(v, 3 if v < 1 else None), False),
        ("Echter Andrang: flüssig bis (Fragen/min)", cap_.get("rate_ok"), per_min, True),
        ("Stocken bei empfohlener Last (p95)", rec_step.get("stall_p95"), lambda v: secs(v), False),
        ("Längster Text (Buchseiten)", pages(ctx.get("max_ok")) if ctx.get("max_ok") else None,
         lambda v: "≈ " + fmt(v, 0), True),
        ("Richtige Antworten unter Last", pr.get("load_pct"), lambda v: fmt(v, 0, " %"), True),
        ("Kosten pro 1.000 Antworten", eco.get("own_per_1000"), lambda v: eur(v, 2), False),
        ("Verlässlichkeit der Messung", q, str, None),
    ]


def change(ref, v, higher_better):
    """(Text, Farbe) für die Veränderung gegenüber der Referenz."""
    if higher_better is None or ref in (None, 0) or v is None:
        return "", INK
    d = (v / ref - 1) * 100
    if abs(d) < 5:
        return "  (≈ gleich)", MUTED
    better = d > 0 if higher_better else d < 0
    return f"  ({'+' if d > 0 else '−'}{fmt(abs(d), 0)} %)", GOOD if better else BAD


def build_compare(summaries, path, labels=None):
    n = len(summaries)
    names = labels if labels and len(labels) == n else [chr(ord("A") + i) for i in range(n)]
    full = [_label(s) for s in summaries]
    figs = [figures(s) for s in summaries]
    d = Deck()

    # ═══ Titel ═══
    sl = d.slide(dark=True)
    text(sl, 0.8, 1.55, 11.5, 0.45, "VERGLEICH", size=15, color="94A3B8", bold=True)
    text(sl, 0.8, 2.0, 11.8, 1.0, " gegen ".join(names), size=40, color="FFFFFF", bold=True,
         font="Cambria")
    text(sl, 0.8, 3.3, 11.8, 2.5, [[(f"{nm}: ", {"bold": True, "color": "FFFFFF"}), (fl, {"color": "CBD5E1"})]
                                   for nm, fl in zip(names, full)], size=17, space_after=6)
    for i in range(min(n, 6)):
        dot(sl, 0.8 + i * 0.35, 6.3, 0.2, COLORS[i])
    notes(sl, "Erzeugt mit llm_stresstest.py --compare. Der erste Lauf ist die Referenz.")

    # ═══ Ergebnis in einem Satz ═══
    sl = d.slide()
    title(sl, "Was ist besser?", f"Referenz ist {names[0]}. Grün = besser, Rot = schlechter als {names[0]} "
                                 "(Unterschiede unter 5 % gelten als gleich).")
    ref_f = figs[0]
    lines = []
    for j in range(1, n):
        for (nm, v, f_, hb), (_, rv, _, _) in zip(figs[j], ref_f):
            if hb is None or v is None or not rv:
                continue
            dlt = (v / rv - 1) * 100
            if abs(dlt) < 5:
                continue
            better = dlt > 0 if hb else dlt < 0
            lines.append((GOOD if better else BAD,
                          f"{names[j]}: {nm} {'besser' if better else 'schlechter'} – {f_(v)} statt {f_(rv)} "
                          f"({'+' if dlt > 0 else '−'}{fmt(abs(dlt), 0)} %)"))
    if not lines:
        lines = [(MUTED, "Kein nennenswerter Unterschied – alle Kennzahlen liegen innerhalb von 5 %.")]
    # Wer reicht für die meisten Nutzer?
    users = [f[0][1] or 0 for f in figs]
    best = max(range(n), key=lambda i: users[i])
    vds = [verdict(s) for s in summaries]
    rect(sl, 0.6, 1.7, W - 1.2, 1.0, DARK_BG)
    text(sl, 0.95, 1.7, W - 1.9, 1.0,
         f"Am meisten Nutzer schafft {names[best]} (≈ {approx(users[best])})." if users[best] else
         "Keiner der Läufe erreicht die Ziele.", size=22, bold=True, color="FFFFFF",
         anchor=MSO_ANCHOR.MIDDLE, font="Cambria")
    rh = min(0.42, 3.6 / max(1, len(lines)))
    for i, (col, t_) in enumerate(lines[:12]):
        yy = 2.95 + i * rh
        dot(sl, 0.65, yy + (rh - 0.18) / 2, 0.18, col)
        text(sl, 0.98, yy, W - 1.6, rh, t_, size=13 if rh >= 0.36 else 11.5, anchor=MSO_ANCHOR.MIDDLE)
    footer(sl, "Urteil je Lauf: " + " · ".join(f"{nm}: {v['headline']}" for nm, v in zip(names, vds)))

    # ═══ Alle Kennzahlen ═══
    sl = d.slide()
    title(sl, "Alle Kennzahlen nebeneinander", "In Klammern: Veränderung gegenüber " + names[0])
    rows = [["Kennzahl"] + names]
    for k in range(len(ref_f)):
        nm, rv, f_, hb = ref_f[k]
        row = [nm, f_(rv) if rv is not None else "–"]
        for j in range(1, n):
            v = figs[j][k][1]
            txt, col = change(rv, v, hb)
            row.append(((f_(v) if v is not None else "–") + txt, col if col != INK else None)
                       if txt else (f_(v) if v is not None else "–"))
        rows.append(row)
    rest = (W - 1.2 - 4.2) / n
    table(sl, 0.6, 1.7, W - 1.2, rows, col_w=[4.2] + [rest] * n, font=12, row_h=0.42)
    footer(sl, "Aktive Nutzer nach dem Gesetz von Little; Kosten = Abschreibung + Strom bei voller Nutzung "
               "während der Arbeitszeit (Annahmen wie im Einzelbericht).")
    notes(sl, "Farbige Werte: grün = besser, rot = schlechter als die Referenz.")

    # ═══ Einstellungen ═══
    sl = d.slide()
    title(sl, "Was war bei den Läufen anders?")
    diff = []
    for key, nm in CONFIG_KEYS:
        vals = [str((s.get("config") or {}).get(key, "–")) for s in summaries]
        if len(set(vals)) > 1:
            diff.append([nm] + vals)
    gpu = [str((s.get("meta") or {}).get("server_max_model_len") or (s.get("meta") or {}).get("max_model_len") or "–")
           for s in summaries]
    if len(set(gpu)) > 1:
        diff.append(["Max. Kontext laut Server"] + gpu)
    diff.append(["Gestartet"] + [(s.get("meta") or {}).get("started", "–").replace("T", " ") for s in summaries])
    table(sl, 0.6, 1.5, W - 1.2, [["Einstellung"] + names] + diff, col_w=[4.2] + [rest] * n, font=12,
          row_h=0.4)
    if len(diff) == 1:
        text(sl, 0.6, 2.5, W - 1.2, 0.8, "Die Testeinstellungen waren gleich – Unterschiede kommen vom "
                                           "Server, vom Modell oder dessen Einstellungen.", size=15, color=INK2)
    footer(sl, "Nur Einstellungen, die sich unterscheiden. Servereinstellungen (z. B. vLLM-Parameter) "
               "kennt der Test nicht – bitte selbst notieren.")

    # ═══ Leistung im Vergleich ═══
    ramps = [sorted((s.get("ramp") or {}).get("steps", []), key=lambda x: x["concurrency"]) for s in summaries]
    if any(ramps):
        sl = d.slide()
        title(sl, "Leistung im Vergleich", "Links: Gesamtleistung · rechts: Wartezeit für fast alle (p95)")
        xy_chart(sl, 0.5, 1.6, 6.1, 5.1, [(nm, [(x["concurrency"], x["out_tps"] or 0) for x in st])
                                          for nm, st in zip(names, ramps) if st],
                 "Tokens pro Sekunde (alle zusammen)", None, "Fragen gleichzeitig", colors=COLORS)
        xy_chart(sl, 6.75, 1.6, 6.1, 5.1, [(nm, [(x["concurrency"], x["ttft_p95"]) for x in st
                                                 if x["ttft_p95"] is not None])
                                           for nm, st in zip(names, ramps) if st],
                 "Sekunden bis zum ersten Wort (p95)", None, "Fragen gleichzeitig", colors=COLORS)
        footer(sl, "Je höher links, desto mehr schafft der Server insgesamt. Je niedriger rechts, desto "
                   "kürzer warten die Nutzer.")

    rates = [sorted((s.get("rate") or {}).get("stages", []), key=lambda x: x["rate"]) for s in summaries]
    if any(rates):
        sl = d.slide()
        title(sl, "Echter Andrang im Vergleich", "Fragen kommen zufällig – wann wird die Schlange zu lang?")
        xy_chart(sl, 0.5, 1.6, 8.2, 5.1, [(nm, [(x["rate"] * 60, x["ttft_p95"]) for x in st
                                                if x["ttft_p95"] is not None])
                                          for nm, st in zip(names, rates) if st],
                 None, "Sekunden bis zum ersten Wort (p95)", "Fragen pro Minute", colors=COLORS)
        caps = [capacity(s) for s in summaries]
        explain(sl, "Nach rechts kommen mehr Fragen pro Minute. Die Linie, die später nach oben "
                    "schießt, verkraftet mehr Andrang.",
                " ".join(f"{nm}: flüssig bis {per_min(c.get('rate_ok'))} Fragen/min"
                         f"{' (≈ ' + approx(c.get('users_rate')) + ' Nutzer)' if c.get('users_rate') else ''}."
                         for nm, c in zip(names, caps)))

    # ═══ Kosten im Vergleich ═══
    ecos = [economics(s) for s in summaries]
    if any(ecos):
        sl = d.slide()
        title(sl, "Kosten im Vergleich")
        rows = [["", *names]]
        for key, nm, f_ in (("own_month", "Eigener Server pro Monat", eur),
                            ("answers_month", "Antworten pro Monat bei voller Nutzung", lambda v: fmt(v, 0)),
                            ("own_per_1000", "Kosten pro 1.000 Antworten", lambda v: eur(v, 2)),
                            ("cloud_per_1000", "Cloud pro 1.000 Antworten", lambda v: eur(v, 2)),
                            ("breakeven_pct", "Günstiger als Cloud ab Auslastung", lambda v: fmt(v, 0, " %")),
                            ("own_per_user", "Pro aktivem Nutzer und Monat", lambda v: eur(v, 2))):
            rows.append([nm] + [f_(e[key]) if e and e.get(key) is not None else "–" for e in ecos])
        table(sl, 0.6, 1.6, W - 1.2, rows, col_w=[4.2] + [rest] * n, font=12, row_h=0.45)
        footer(sl, "Mehr Antworten pro Monat bei gleichen Kosten = günstiger pro Antwort. "
                   "Annahmen (Preis, Strom, Cloud-Tarif) aus den jeweiligen Läufen.")

    # ═══ Antwortqualität im Vergleich ═══
    prs = [s.get("probes") for s in summaries]
    if any(p and p.get("load_pct") is not None for p in prs):
        sl = d.slide()
        title(sl, "Antwortqualität im Vergleich", "Anteil richtig beantworteter Kontrollfragen")
        rows = [["", *names],
                ["ohne Last"] + [fmt(p.get("alone_pct"), 0, " %") if p else "–" for p in prs],
                ["unter Last"] + [fmt(p.get("load_pct"), 0, " %") if p else "–" for p in prs],
                ["schlechteste Stufe"] + [f"{p['worst']['label']}: {fmt(p['worst']['pct'], 0)} %"
                                          if p and p.get("worst") else "–" for p in prs]]
        table(sl, 0.6, 1.6, W - 1.2, rows, col_w=[4.2] + [rest] * n, font=12, row_h=0.45)

    d.save(path)
    return path
