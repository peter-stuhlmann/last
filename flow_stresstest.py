#!/usr/bin/env python3
"""
Lasttest für Abläufe („Ablauf“): anmelden, Seite öffnen, etwas tun – zum Beispiel mit einem Chat reden.

Zwei Teile:

  Aufzeichnen   Ein echter Browser (Chromium, unsichtbar) führt die Schritte aus dem Formular aus.
                Ab der Zeile „messen ab hier“ schneidet er mit, welche Anfragen die Seite an den
                Server schickt – samt Cookies, Kopfzeilen und Antworten – und macht pro Schritt
                ein Bildschirmfoto. Werte, die aus einer früheren Antwort stammen (z. B. eine
                Chat-ID), werden erkannt und als veränderlich markiert.

  Abspielen     Unter Last werden nur noch diese Anfragen gestellt, ohne Browser: hunderte
                gleichzeitig. Jede Wiederholung holt sich die veränderlichen Werte frisch.
                Gemessen wird „Zeit bis zum ersten Wort“ (erste Daten der Hauptanfrage, meist der
                gestreamten Antwort) und „Antwort fertig“ (der ganze Messbereich).

Die Lastgeneratoren und Testschritte kommen aus web_stresstest.py. Zugangsdaten stehen in
Platzhaltern ({email}, {passwort}) und werden nirgends gespeichert; die Aufzeichnung mit
Sitzungs-Cookies lebt nur im Arbeitsspeicher des laufenden Tests.
"""

import json
import re
import time
from urllib.parse import urlsplit

import aiohttp
from yarl import URL

import llm_stresstest as lt
from llm_stresstest import fmt, log
from web_stresstest import USER_AGENT, WebClient, WebStressTest, _CachingResolver


def browser_available():
    """Ist Playwright (und damit der unsichtbare Browser) installiert? Im schlanken Image nicht."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


NO_BROWSER = ("Dieses Backend-Image enthält keinen Browser. Für Abläufe das Image-Ziel „browser“ bauen: "
              "docker compose up --build ohne BACKEND_TARGET=slim (bzw. make up ohne SLIM=1).")

FLOW_DEFAULTS = {"levels": "1,2,4,8,16,32", "slo_load": 10.0, "spike_size": 16, "include_assets": False,
                 "think_time": 60.0, "timeout": 120.0, "break_load": 90.0}
MAX_STEPS_TEXT = 20 * 1024
STEP_TIMEOUT_MS = 30_000
MAX_RESPONSE = 2 * 1024 * 1024          # so viel einer Antwort wird bei der Aufzeichnung behalten
RECORD_TYPES = {"xhr", "fetch", "document", "eventsource", "other"}
HOP_HEADERS = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade",
               "te", "trailer", "proxy-authorization", "cookie", "accept-encoding", "user-agent"}
SECRET_HEADERS = {"authorization", "cookie", "x-api-key", "x-csrf-token", "x-xsrf-token"}

# ════════════════════════════════════════════════════════════════════════════
#  Schritt-Sprache
# ════════════════════════════════════════════════════════════════════════════

_Q = r'"([^"]+)"'
_NUM = r"(\d+(?:[.,]\d+)?)"
# Gibt es ein Feld oder einen Knopf mehrfach: „bei“ nennt Text in der Nähe, „(Nr. 2)“ zählt in Lesereihenfolge
_WHERE = r'(?:\s+bei\s+"([^"]+)")?(?:\s*\(Nr\.\s*(\d{1,3})\))?'
PATTERNS = [
    ("open", re.compile(r"^öffne\s+(\S+)$", re.I)),
    ("fill", re.compile(r"^tippe in\s+" + _Q + _WHERE + r"\s+(.+)$", re.I)),
    ("click", re.compile(r"^klicke\s+" + _Q + _WHERE + r"$", re.I)),
    ("press", re.compile(r"^drücke\s+(\w+)$", re.I)),
    ("wait_text", re.compile(r"^warte auf text\s+" + _Q + r"$", re.I)),
    ("wait_first", re.compile(r"^warte auf erste antwort in\s+" + _Q + r"$", re.I)),
    ("wait_quiet", re.compile(r"^warte bis die seite ruhig ist(?:\s*\(" + _NUM + r"\s*s\))?$", re.I)),
    ("wait_done", re.compile(r"^warte bis\s+" + _Q + r"\s+fertig ist(?:\s*\(" + _NUM + r"\s*s ruhig\))?$", re.I)),
    ("wait_sel", re.compile(r"^warte auf\s+" + _Q + r"$", re.I)),
    ("wait_s", re.compile(r"^warte\s+" + _NUM + r"\s*s$", re.I)),
    ("measure", re.compile(r"^[─\-—=\s]*messen(?:\s+ab\s+hier)?[─\-—=\s]*$", re.I)),
]
PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w-]*)\}")
KEYS = {"enter": "Enter", "tab": "Tab", "escape": "Escape", "esc": "Escape"}


def _num(s):
    return float(s.replace(",", "."))


def _where(m):
    """„bei …“ und „(Nr. …)“ – nur, wenn sie in der Zeile stehen."""
    out = {}
    if m.group(2):
        out["near"] = m.group(2)
    if m.group(3) and int(m.group(3)) >= 1:
        out["nth"] = int(m.group(3))
    return out


def _fmt_num(x):
    return f"{x:g}".replace(".", ",")


def format_step(step):
    """Gegenstück zu parse_steps: ein Schritt als Zeile – so, wie ihn die Oberfläche anzeigt und zurückschickt."""
    k = step["kind"]
    where = (f' bei "{step["near"]}"' if step.get("near") else "") + (f" (Nr. {step['nth']})" if step.get("nth") else "")
    if k == "open":
        return f"öffne {step['url']}"
    if k == "fill":
        text = step["text"]
        return f'tippe in "{step["target"]}"{where} ' + (text if PLACEHOLDER.fullmatch(text) else f'"{text}"')
    if k == "click":
        return f'klicke "{step["target"]}"{where}'
    if k == "press":
        return f"drücke {step['key']}"
    if k == "wait_quiet":
        return f"warte bis die Seite ruhig ist ({_fmt_num(step['quiet'])} s)"
    if k == "wait_s":
        return f"warte {_fmt_num(step['seconds'])} s"
    if k == "measure":
        return "messen ab hier"
    raise ValueError(f"Unbekannte Art von Schritt: {k}")


def parse_steps(text, partial=False):
    """Schritte aus dem Formular → Liste von Dicts. Meldet Fehler mit Zeilennummer.
    partial=True: ein angefangener Ablauf zum Abtasten der Seite – „messen ab hier“ ist dann freiwillig."""
    if len(text or "") > MAX_STEPS_TEXT:
        raise ValueError("Der Ablauf ist zu lang (höchstens 20 kB).")
    steps = []
    for n, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for kind, pat in PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            step = {"kind": kind, "line": n}
            if kind == "open":
                url = m.group(1).strip("\"'")
                if not url.startswith(("http://", "https://")):
                    raise ValueError(f"Zeile {n}: „öffne“ braucht eine Adresse mit http:// oder https://")
                step["url"] = url
            elif kind == "fill":
                value = m.group(4).strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                step.update(target=m.group(1), text=value, **_where(m))
            elif kind == "click":
                step.update(target=m.group(1), **_where(m))
            elif kind in ("wait_text", "wait_first", "wait_sel"):
                step["target"] = m.group(1)
            elif kind == "press":
                key = m.group(1)
                step["key"] = KEYS.get(key.lower(), key)
            elif kind == "wait_done":
                step.update(target=m.group(1), quiet=_num(m.group(2)) if m.group(2) else 3.0)
            elif kind == "wait_quiet":
                step["quiet"] = min(30.0, _num(m.group(1))) if m.group(1) else 2.0
            elif kind == "wait_s":
                step["seconds"] = min(60.0, _num(m.group(1)))
            steps.append(step)
            break
        else:
            raise ValueError(f"Zeile {n}: „{line[:60]}“ verstehe ich nicht. Erlaubt sind: öffne, tippe in, "
                             "klicke, drücke, warte auf Text, warte auf, warte N s, messen ab hier, "
                             "warte auf erste Antwort in, warte bis … fertig ist, warte bis die Seite ruhig ist.")
    kinds = [s["kind"] for s in steps]
    if partial:
        if not kinds or kinds[0] != "open":
            raise ValueError("Der Ablauf muss mit „öffne https://…“ beginnen.")
        if kinds.count("measure") > 1:
            raise ValueError("„messen ab hier“ darf nur einmal vorkommen.")
        return steps
    if kinds.count("measure") != 1:
        raise ValueError("Genau eine Zeile „messen ab hier“ ist nötig – davor Anmeldung und Vorbereitung, "
                         "danach das, was gemessen werden soll.")
    if not kinds or kinds[0] != "open":
        raise ValueError("Der Ablauf muss mit „öffne https://…“ beginnen.")
    if kinds.index("measure") == len(kinds) - 1:
        raise ValueError("Nach „messen ab hier“ muss mindestens ein Schritt folgen.")
    return steps


def placeholders(steps):
    """Namen der Platzhalter ({email}, {passwort}) in Reihenfolge ihres ersten Auftretens."""
    out = []
    for s in steps:
        for name in PLACEHOLDER.findall(s.get("text") or ""):
            if name not in out:
                out.append(name)
    return out


def fill_text(text, secrets):
    def sub(m):
        name = m.group(1)
        if name not in secrets:
            raise ValueError(f"Für den Platzhalter {{{name}}} fehlt ein Wert.")
        return secrets[name]
    return PLACEHOLDER.sub(sub, text)


def is_selector(target):
    """CSS-Selektor (#id, .klasse, [attr], div > p) oder sichtbarer Text?"""
    t = target.strip()
    return bool(t) and (t[0] in "#.[" or any(ch in t for ch in "<>=") or bool(re.match(r"^[a-z]+[.#\[]", t)))


# ════════════════════════════════════════════════════════════════════════════
#  Aus der Aufzeichnung einen abspielbaren Plan machen
# ════════════════════════════════════════════════════════════════════════════

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,}")


def _json_paths(value, path=()):
    """Alle Blätter eines JSON-Werts mit ihrem Pfad."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _json_paths(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _json_paths(v, path + (i,))
    else:
        yield path, value


def _leaf_index(record):
    """Suchindex: Wert → Pfad in der Antwort (JSON) oder Kopfzeile."""
    index = {}
    body = record.get("resp_body")
    if body:
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            parsed = None
        if parsed is not None:
            for path, leaf in _json_paths(parsed):
                if isinstance(leaf, (str, int)) and len(str(leaf)) >= 8:
                    index.setdefault(str(leaf), list(path))
    # Aus Antwort-Kopfzeilen nur solche, die typischerweise IDs tragen (Location, X-…)
    for name, value in (record.get("resp_headers") or {}).items():
        if name.lower() == "location" or name.lower().startswith("x-"):
            for tok in TOKEN.findall(value or ""):
                index.setdefault(tok, ["$header", name])
    return index


def _clean_headers(headers):
    return {k: v for k, v in (headers or {}).items()
            if k.lower() not in HOP_HEADERS and not k.lower().startswith((":", "sec-"))}


def build_plan(records):
    """Aufzeichnung → Plan: Anfragen als Vorlagen, veränderliche Werte als {{v1}} mit Herkunft."""
    requests, extract, var_of = [], {}, {}
    indexes = []
    main = next((r["i"] for r in records if r.get("stream")), None)
    if main is None and records:
        main = max(records, key=lambda r: (r.get("t_end") or 0) - (r.get("t_start") or 0))["i"]
    for rec in records:
        tpl = {"method": rec["method"], "url": rec["url"], "headers": _clean_headers(rec.get("headers")),
               "body": rec.get("body") or "", "status": rec.get("status") or 200, "stream": bool(rec.get("stream")),
               "dynamic": []}
        # Veränderliche Werte stecken in Adresse, Body oder eigenen (X-…) Kopfzeilen – nicht in Content-Type & Co.
        searchable = [tpl["url"], tpl["body"]] + [v for k, v in tpl["headers"].items()
                                                  if k.lower().startswith("x-") and k.lower() not in SECRET_HEADERS]
        for tok in sorted({t for s in searchable for t in TOKEN.findall(s)}, key=len, reverse=True):
            if tok in var_of:
                source = None
            else:
                source = next(((i, idx[tok]) for i, idx in enumerate(indexes) if tok in idx), None)
                if source is None:
                    continue
                var_of[tok] = f"v{len(var_of) + 1}"
                extract[var_of[tok]] = {"from": source[0], "path": source[1]}
            var = var_of[tok]
            marker = "{{" + var + "}}"
            tpl["url"] = tpl["url"].replace(tok, marker)
            tpl["body"] = tpl["body"].replace(tok, marker)
            tpl["headers"] = {k: (v.replace(tok, marker) if k.lower() not in SECRET_HEADERS else v)
                              for k, v in tpl["headers"].items()}
            tpl["dynamic"].append(var)
        requests.append(tpl)
        indexes.append(_leaf_index(rec))
    return {"requests": requests, "extract": extract, "main": main or 0, "cookies": []}


def render(template, variables):
    for name, value in variables.items():
        template = template.replace("{{" + name + "}}", str(value))
    return template


def public_plan(plan):
    """Die Kurzfassung für Ergebnis und Bericht – ohne Werte, die Zugangsdaten enthalten könnten."""
    out = []
    for tpl in plan["requests"]:
        parts = urlsplit(tpl["url"])
        out.append({"method": tpl["method"], "host": parts.netloc, "path": parts.path or "/",
                    "query": bool(parts.query), "status": tpl["status"], "stream": tpl["stream"],
                    "body_bytes": len(tpl["body"].encode("utf-8")), "header_names": sorted(tpl["headers"]),
                    "dynamic": tpl["dynamic"]})
    return out


def _dig(data, path):
    if path and path[0] == "$header":
        return None
    for key in path:
        try:
            data = data[key]
        except (KeyError, IndexError, TypeError):
            return None
    return data


# ════════════════════════════════════════════════════════════════════════════
#  Abspielen per HTTP
# ════════════════════════════════════════════════════════════════════════════

class FlowClient(WebClient):
    """Ein „request“ ist ein kompletter Messbereich: alle aufgezeichneten Anfragen nacheinander,
    mit frisch geholten veränderlichen Werten. Ohne Plan wird beim ersten prepare() aufgezeichnet."""

    def __init__(self, args, plan=None, outdir=None):
        super().__init__(args)
        # Ein Plan je Konto; unter Last kommen die Konten reihum dran
        self.plans = list(plan) if isinstance(plan, list) else ([plan] if plan else None)
        self.outdir = outdir
        self.record_info = None
        self._turn = 0

    @property
    def plan(self):
        return self.plans[0] if self.plans else None

    async def __aenter__(self):
        self.resolver = _CachingResolver()
        return self

    async def __aexit__(self, *exc):
        await self.resolver.close()

    def _session(self, plan):
        jar = aiohttp.CookieJar(unsafe=True)
        for c in plan.get("cookies") or []:
            scheme = "https" if c.get("secure") else "http"
            jar.update_cookies({c["name"]: c["value"]},
                               response_url=URL(f"{scheme}://{c.get('domain', '').lstrip('.')}{c.get('path') or '/'}"))
        connector = aiohttp.TCPConnector(limit=0, limit_per_host=6, resolver=self.resolver)
        return aiohttp.ClientSession(connector=connector, cookie_jar=jar, headers={"User-Agent": USER_AGENT})

    async def prepare(self):
        if self.plans is None:
            from flow_recorder import record  # Playwright nur laden, wenn wirklich aufgezeichnet wird
            self.plans, self.record_info = await record(self.args, self.outdir)
        return self.record_info or {"status": 200, "bytes": 0, "assets": len(self.plan["requests"]), "files": [],
                                    "total_bytes": 0, "final_url": self.args.base_url, "rtt_ms": None, "busy": None,
                                    "requests": public_plan(self.plan), "main": self.plan["main"], "steps": [],
                                    "accounts": len(self.plans)}

    async def _view(self, r, t0):
        plan = self.plans[self._turn % len(self.plans)]
        self._turn += 1
        needed = {src["from"] for src in plan["extract"].values()}
        variables, responses = {}, {}
        r["chunks"] = 0
        async with self._session(plan) as session:
            for k, tpl in enumerate(plan["requests"]):
                url = render(tpl["url"], variables)
                headers = {h: render(v, variables) for h, v in tpl["headers"].items()}
                body = render(tpl["body"], variables).encode("utf-8") if tpl["body"] else None
                async with session.request(tpl["method"], url, data=body, headers=headers,
                                           allow_redirects=False) as resp:
                    t_headers = time.perf_counter()
                    size, chunks, text = 0, 0, b""
                    async for chunk in resp.content.iter_any():
                        if k == plan["main"] and r["ttft"] is None and chunk:
                            r["ttft"], r["tp_first"] = time.perf_counter() - t0, time.perf_counter()
                        size += len(chunk)
                        chunks += 1
                        if k in needed and len(text) < MAX_RESPONSE:
                            text += chunk
                    r["requests"] += 1
                    r["bytes"] += size
                    if k == plan["main"]:
                        r["status"], r["chunks"] = resp.status, chunks
                        if r["ttft"] is None:
                            r["ttft"], r["tp_first"] = t_headers - t0, t_headers
                    if resp.status // 100 != tpl["status"] // 100:
                        r["error"] = f"http_{resp.status}"
                        return
                    if k in needed:
                        try:
                            responses[k] = json.loads(text.decode("utf-8", "replace"))
                        except ValueError:
                            responses[k] = None
                        for var, src in plan["extract"].items():
                            if src["from"] == k:
                                value = _dig(responses[k], src["path"]) if src["path"][:1] != ["$header"] \
                                    else resp.headers.get(src["path"][1])
                                if value is None:
                                    r["error"] = "wert_fehlt"
                                    r["error_detail"] = f"{var} aus Anfrage {k + 1} nicht gefunden"
                                    return
                                variables[var] = value
        r["ok"] = True


# ════════════════════════════════════════════════════════════════════════════
#  Der Testlauf
# ════════════════════════════════════════════════════════════════════════════

class FlowStressTest(WebStressTest):
    def __init__(self, args, outdir):
        super().__init__(args, outdir)
        cfg = self.summary["config"]
        # Zugangsdaten raus, Schritte als Text rein (ohne eingesetzte Werte)
        cfg.pop("secrets", None)
        cfg.pop("accounts", None)
        cfg.pop("steps", None)
        cfg["steps_text"] = args.steps_text
        cfg["placeholders"] = placeholders(args.steps)
        cfg["accounts"] = len(getattr(args, "accounts", None) or [args.secrets])

    def make_client(self):
        return FlowClient(self.a, outdir=self.outdir)

    async def preflight(self, client):
        log("Vorbereitung: Ablauf im Browser aufzeichnen …")
        self.summary["meta"].update({"started": lt.dt.datetime.now().isoformat(timespec="seconds"),
                                     "host": lt.platform.node(),
                                     "server_host": urlsplit(self.a.base_url).hostname})
        info = await client.prepare()
        self.summary["prechecks"] = info
        reqs = info.get("requests") or []
        main = reqs[info.get("main", 0)] if reqs else None
        log(f"  Aufgezeichnet: {len(info.get('steps') or [])} Schritte, {len(reqs)} Anfragen im Messbereich"
            + (f" · Hauptanfrage {main['method']} {main['path']}" + (" (gestreamt)" if main["stream"] else "")
               if main else ""))
        if info.get("accounts", 1) > 1:
            log(f"  {info['accounts']} Konten aufgezeichnet – unter Last kommen sie reihum dran")
        dyn = sum(len(q["dynamic"]) for q in reqs)
        if dyn:
            log(f"  {dyn} veränderliche{'r' if dyn == 1 else ''} Wert{'' if dyn == 1 else 'e'} erkannt – wird bei jeder "
                "Wiederholung frisch geholt")
        if info.get("rtt_ms") is not None:
            log(f"  Erstes Wort nach {fmt(info['rtt_ms'], 0)} ms")
        self.notify()
