#!/usr/bin/env python3
"""
Lasttest für Websites
=====================

Simuliert Besucher, die eine Seite aufrufen: erst das HTML, dann – wie ein Browser beim
ersten Besuch – die Bilder, Styles und Skripte derselben Website. Gemessen wird

  - Erste Antwort:   Zeit, bis der Server die ersten Daten schickt (TTFB)
  - Ladezeit:        Zeit, bis die Seite samt Dateien vollständig da ist
  - Seiten/Sekunde:  wie viele Seitenaufrufe der Server insgesamt schafft
  - Fehler:          Aufrufe mit Fehlerseite, Abbruch oder Zeitüberschreitung

Die Lastgeneratoren (feste Parallelität, zufällige Ankünfte, Ansturm) kommen aus
llm_stresstest.py; das Ergebnis hat dieselbe Form, damit die Oberfläche es anzeigen kann.

Nur gegen eigene Websites einsetzen. Der Test gibt sich im User-Agent zu erkennen.
Wird von stresstest_web.py gestartet (Feld „kind": "web").
"""

import argparse
import asyncio
import datetime as dt
import json
import os
import platform
import random
import re
import time
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import aiohttp

import llm_stresstest as lt
from llm_stresstest import fmt, log, mean, pct

USER_AGENT = "LAST-Lasttest/1.0 (Lasttest der eigenen Website oder API)"
MAX_ASSETS = 60                    # mehr Dateien pro Seite lädt der Test nicht
MAX_BODY = 20 * 1024 * 1024        # pro Datei höchstens 20 MB lesen
MAX_HTML = 2 * 1024 * 1024         # so viel HTML wird nach Dateien durchsucht
PER_HOST = 6                       # so viele Verbindungen öffnet ein Browser pro Website
TESTS = ("baseline", "ramp", "rate", "spike", "soak")

# Standardwerte („Gründlich“) und das Schnell-Profil – dieselbe Idee wie beim KI-Server-Test
DEFAULTS = {
    "base_url": "", "tests": ",".join(TESTS),
    "levels": "1,2,4,8,16,32,64,128,256", "level_seconds": 60.0, "warmup_seconds": 10.0,
    "min_samples": 40, "baseline_requests": 10, "rate_seconds": 60.0,
    "spike_size": 64, "spike_idle": 5.0, "soak_minutes": 15.0, "cooldown": 5.0,
    "think_time": 30.0, "target_users": 0, "slo_load": 3.0, "include_assets": True,
    "timeout": 30.0, "max_error_rate": 0.05, "break_load": 30.0, "monitor_interval": 2.0,
    "seed": None,
}
QUICK_PROFILE = {"levels": "1,4,16,32,64", "level_seconds": 30, "warmup_seconds": 5,
                 "min_samples": 20, "baseline_requests": 5, "rate_seconds": 30,
                 "spike_size": 32, "soak_minutes": 3}

# HTTP-API: gleiche Schritte, aber eine einzelne Anfrage statt einer Seite mit Dateien.
# Ziel: Antwort nach höchstens 0,5 s. Bei APIs zählt nicht die Zahl der Nutzer, sondern
# wie viele Anfragen pro Minute flüssig durchgehen – „target_users“ meint hier genau das.
API_DEFAULTS = {"slo_load": 0.5, "include_assets": False, "method": "GET", "headers": {},
                "body": "", "expect_status": "2xx"}
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
MAX_API_BODY = 64 * 1024
MAX_HEADERS = 20
# Diese Kopfzeilen setzt der Test selbst oder sie würden die Verbindung manipulieren
FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade",
                     "user-agent", "expect", "te", "trailer", "keep-alive", "proxy-authorization"}
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")

WORDS = {
    "web": {"subject": "Die Website", "subj": "die Website", "units": "Besucher", "time": "Ladezeit", "events": "Aufrufe",
            "one": "ein Besucher", "fail": "eine Fehlerseite", "stand": "dem Andrang"},
    "api": {"subject": "Die API", "subj": "die API", "units": "Anfragen", "time": "Antwortzeit", "events": "Anfragen",
            "one": "eine Anfrage", "fail": "einen Fehler", "stand": "der Last"},
    "flow": {"subject": "Die Anwendung", "subj": "die Anwendung", "units": "Nutzer", "time": "Antwortzeit",
             "events": "Durchläufe", "one": "ein Nutzer", "fail": "einen Fehler", "stand": "dem Andrang"},
}


def words(cfg):
    kind = (cfg or {}).get("kind")
    return WORDS[kind if kind in WORDS else "web"]


def status_ok(status, expect):
    """Passt der Status zur Erwartung? „2xx“ = 200–299, sonst genau diese Zahl."""
    expect = str(expect)
    if expect.endswith("xx"):
        return status // 100 == int(expect[0])
    return status == int(expect)


def parse_headers(raw):
    """Kopfzeilen aus dem Formular ([{name, value}] oder {name: value}) prüfen."""
    items = list(raw.items()) if isinstance(raw, dict) else [
        (h.get("name", ""), h.get("value", "")) for h in (raw or []) if isinstance(h, dict)]
    if len(items) > MAX_HEADERS:
        raise ValueError(f"Höchstens {MAX_HEADERS} Kopfzeilen")
    out = {}
    for name, value in items:
        name, value = str(name).strip(), str(value).strip()
        if not _HEADER_NAME.match(name):
            raise ValueError(f"Ungültiger Name einer Kopfzeile: {name!r}")
        if name.lower() in FORBIDDEN_HEADERS:
            raise ValueError(f"Die Kopfzeile {name} setzt der Test selbst")
        if len(value) > 2048 or any(ord(ch) < 32 or ch == "\x7f" for ch in value):
            raise ValueError(f"Ungültiger Wert für Kopfzeile {name}")
        out[name] = value
    return out


def build_args(cfg):
    """JSON aus dem Formular → Namespace. Unbekannte Felder werden ignoriert."""
    kind = cfg.get("kind") if cfg.get("kind") in ("api", "flow") else "web"
    defaults = {**DEFAULTS, **API_DEFAULTS}
    if kind == "web":
        defaults.update(slo_load=DEFAULTS["slo_load"], include_assets=DEFAULTS["include_assets"])
    elif kind == "flow":
        from flow_stresstest import FLOW_DEFAULTS
        defaults.update(FLOW_DEFAULTS)
    a = argparse.Namespace(kind=kind, **defaults)
    if kind == "flow":
        # Der Ablauf bestimmt die Adresse selbst (erste „öffne“-Zeile)
        from flow_stresstest import parse_steps, placeholders
        a.steps_text = str(cfg.get("steps") or "")
        a.steps = parse_steps(a.steps_text)
        raw_secrets = cfg.get("secrets") if isinstance(cfg.get("secrets"), dict) else {}
        a.secrets = {str(k): str(v)[:1024] for k, v in raw_secrets.items()}
        missing = [p for p in placeholders(a.steps) if p not in a.secrets]
        if missing:
            raise ValueError(f"Für den Platzhalter {{{missing[0]}}} fehlt ein Wert.")
        cfg = {**cfg, "base_url": a.steps[0]["url"]}
    for key, default in DEFAULTS.items():
        val = cfg.get(key)
        if val is None or val == "":
            continue
        try:
            if isinstance(default, bool):
                val = bool(val)
            elif isinstance(default, int):
                val = int(float(val))
            elif isinstance(default, float):
                val = float(val)
            elif key == "seed":
                val = int(float(val))
            else:
                val = str(val).strip()
        except (TypeError, ValueError):
            raise ValueError(f"Ungültiger Wert für {key}: {val!r}") from None
        setattr(a, key, val)
    if not a.base_url.startswith(("http://", "https://")):
        raise ValueError("Adresse muss mit http:// oder https:// beginnen")
    a.tests = ",".join(t for t in (x.strip() for x in a.tests.split(",")) if t in TESTS)
    try:
        if not [int(x) for x in a.levels.split(",") if x.strip()]:
            raise ValueError
    except ValueError:
        raise ValueError("Stufen: ganze Zahlen mit Komma trennen") from None
    if kind == "api":
        a.include_assets = False
        a.method = str(cfg.get("method") or "GET").strip().upper()
        if a.method not in METHODS:
            raise ValueError(f"Methode muss eine von {', '.join(METHODS)} sein")
        a.headers = parse_headers(cfg.get("headers"))
        a.body = str(cfg.get("body") or "")
        if len(a.body.encode("utf-8")) > MAX_API_BODY:
            raise ValueError(f"Body höchstens {MAX_API_BODY // 1024} kB")
        a.expect_status = str(cfg.get("expect_status") or "2xx").strip().lower()
        if not re.match(r"^([1-5]xx|[1-5]\d\d)$", a.expect_status):
            raise ValueError("Erwarteter Status: z. B. 2xx oder 201")
        a.slo_load = float(cfg.get("slo_load") or API_DEFAULTS["slo_load"])
    if kind == "flow":
        a.include_assets = False
    return a


# ════════════════════════════════════════════════════════════════════════════
#  Seite laden wie ein Besucher
# ════════════════════════════════════════════════════════════════════════════

class _AssetParser(HTMLParser):
    """Sammelt die Dateien, die ein Browser zum Anzeigen der Seite sofort nachlädt."""
    LINK_RELS = {"stylesheet", "icon", "preload", "modulepreload"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if tag == "link":
            rels = set((at.get("rel") or "").lower().split())
            if rels & self.LINK_RELS and at.get("href"):
                self.urls.append(at["href"])
        elif tag in ("script", "img") and at.get("src"):
            self.urls.append(at["src"])


def find_assets(html, base_url):
    """Bilder, Styles und Skripte derselben Website (fremde Server werden nie angefragt)."""
    parser = _AssetParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    host = urlparse(base_url).netloc.lower()
    out = []
    for ref in parser.urls:
        url = urljoin(base_url, ref.strip()).split("#")[0]
        p = urlparse(url)
        if p.scheme in ("http", "https") and p.netloc.lower() == host and url not in out:
            out.append(url)
            if len(out) >= MAX_ASSETS:
                break
    return out


class _CachingResolver(aiohttp.abc.AbstractResolver):
    """Jeder Besucher bekommt eigene Verbindungen, aber die Namensauflösung (DNS)
    wird nur einmal gemacht – sonst würde der Test vor allem den DNS-Server belasten."""

    def __init__(self):
        self._inner = aiohttp.DefaultResolver()
        self._cache = {}

    async def resolve(self, host, port=0, family=0):
        key = (host, port, family)
        if key not in self._cache:
            self._cache[key] = await self._inner.resolve(host, port, family)
        return self._cache[key]

    async def close(self):
        await self._inner.close()


class WebClient:
    """Ein „request“ ist ein kompletter Seitenaufruf eines neuen Besuchers
    (ohne Browser-Cache, mit eigenen Verbindungen)."""

    blank_result = staticmethod(lt.Client.blank_result)

    def __init__(self, args):
        self.args = args
        self.url = args.base_url
        self.assets = []
        self.resolver = None

    async def __aenter__(self):
        self.resolver = _CachingResolver()
        return self

    async def __aexit__(self, *exc):
        await self.resolver.close()

    def _session(self):
        connector = aiohttp.TCPConnector(limit=0, limit_per_host=PER_HOST, resolver=self.resolver)
        return aiohttp.ClientSession(
            connector=connector, cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})

    @staticmethod
    async def _get(session, url, keep=0):
        """Lädt eine Adresse. Liefert (Status, Bytes, Zeitpunkt der ersten Antwort, Anfang des
        Inhalts, endgültige Adresse)."""
        async with session.get(url, allow_redirects=True, max_redirects=5) as resp:
            t_first = time.perf_counter()
            size, head = 0, b""
            async for chunk in resp.content.iter_chunked(65536):
                size += len(chunk)
                if len(head) < keep:
                    head += chunk[:keep - len(head)]
                if size >= MAX_BODY:
                    break
            return resp.status, size, t_first, head, str(resp.url)

    async def prepare(self):
        """Erster Aufruf: Ist die Seite erreichbar, und welche Dateien gehören dazu?"""
        t0 = time.perf_counter()
        try:
            async with self._session() as session:
                status, size, t_first, head, final = await asyncio.wait_for(
                    self._get(session, self.url, keep=MAX_HTML), self.args.timeout)
                if status >= 400:
                    raise lt.PreflightError(f"Die Website antwortet mit Fehler {status} – "
                                            "bitte die Adresse prüfen.")
                assets, files = [], []
                if self.args.include_assets:
                    candidates = find_assets(head.decode("utf-8", "replace"), final)

                    async def check(u):
                        t = time.perf_counter()
                        try:
                            st, nbytes, *_ = await self._get(session, u)
                        except Exception:
                            return None
                        if st >= 400:
                            return None
                        return {"url": u, "path": urlparse(u).path or "/", "bytes": nbytes,
                                "ms": (time.perf_counter() - t) * 1000}
                    # Dateien, die schon ohne Last fehlen, würden jede Messung als Fehler zählen
                    files = [f for f in await asyncio.gather(*map(check, candidates)) if f]
                    assets = [f["url"] for f in files]
        except lt.PreflightError:
            raise
        except Exception:
            hint = ""
            if lt.IN_DOCKER and (urlparse(self.url).hostname or "") in ("localhost", "127.0.0.1", "::1"):
                hint = (" Hinweis: Im Docker-Container ist „localhost“ der Container selbst – für eine "
                        "Website auf diesem Rechner host.docker.internal statt localhost eintragen.")
            raise lt.PreflightError(f"Website unter {self.url} nicht erreichbar.{hint}") from None
        self.url, self.assets = final, assets
        # Die größten Dateien für den Bericht: Sie bestimmen meist die Ladezeit
        biggest = sorted(files, key=lambda f: f["bytes"], reverse=True)[:8]
        return {"status": status, "bytes": size, "assets": len(assets), "final_url": final,
                "total_bytes": size + sum(f["bytes"] for f in files),
                "files": [{k: f[k] for k in ("path", "bytes", "ms")} for f in biggest],
                "rtt_ms": (t_first - t0) * 1000, "busy": None}

    async def _view(self, r, t0):
        async with self._session() as session:
            status, size, t_first, _, _ = await self._get(session, self.url)
            r["ttft"], r["tp_first"], r["status"] = t_first - t0, t_first, status
            r["bytes"], r["requests"] = size, 1
            if status >= 400:
                r["error"] = f"http_{status}"
                return
            if self.assets:
                parts = await asyncio.gather(*(self._get(session, u) for u in self.assets))
                r["requests"] += len(parts)
                r["bytes"] += sum(p[1] for p in parts)
                bad = [p[0] for p in parts if p[0] >= 500 or p[0] == 429]
                if bad:
                    r["error"] = f"http_{bad[0]}"
                    return
            r["ok"] = True

    async def request(self, msgs=None, n_out=0, timeout=None, probe=False):
        """Ein Seitenaufruf. Signatur wie beim KI-Client, damit die Lastgeneratoren passen."""
        r = self.blank_result()
        r["bytes"], r["requests"] = 0, 0
        t0 = r["tp_start"]
        try:
            await asyncio.wait_for(self._view(r, t0), timeout or self.args.timeout)
        except TimeoutError:
            r["ok"], r["error"] = False, "timeout"
        except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError,
                ConnectionResetError, aiohttp.ClientOSError) as e:
            r["ok"], r["error"], r["error_detail"] = False, "verbindung", str(e)[:200]
        except Exception as e:  # noqa
            r["ok"], r["error"], r["error_detail"] = False, type(e).__name__, str(e)[:200]
        r["tp_last"] = time.perf_counter()
        r["e2e"] = r["tp_last"] - t0
        return r


class ApiClient(WebClient):
    """Eine HTTP-Anfrage je „request“ – mit Methode, Kopfzeilen und Body aus dem Formular.
    Anders als Besucher einer Website halten API-Clients ihre Verbindungen offen; deshalb teilen
    sich alle simulierten Clients einen Verbindungspool (Keep-Alive)."""

    def __init__(self, args):
        super().__init__(args)
        self.session = None

    async def __aenter__(self):
        self.resolver = _CachingResolver()
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=0, resolver=self.resolver),
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*;q=0.8", **self.args.headers})
        return self

    async def __aexit__(self, *exc):
        await self.session.close()
        await self.resolver.close()

    async def _call(self):
        """Liefert (Status, Bytes, Zeitpunkt der ersten Antwort). Weiterleitungen werden nicht
        verfolgt – ein 3xx ist eine Antwort wie jede andere und wird an der Erwartung gemessen."""
        a = self.args
        extra = {}
        if a.body and not any(k.lower() == "content-type" for k in a.headers):
            extra["Content-Type"] = "application/json"   # die übliche Annahme, wenn nichts angegeben ist
        async with self.session.request(a.method, self.url, data=a.body.encode("utf-8") if a.body else None,
                                        headers=extra, allow_redirects=False) as resp:
            t_first = time.perf_counter()
            size = 0
            async for chunk in resp.content.iter_chunked(65536):
                size += len(chunk)
                if size >= MAX_BODY:
                    break
            return resp.status, size, t_first

    async def prepare(self):
        t0 = time.perf_counter()
        try:
            status, size, t_first = await asyncio.wait_for(self._call(), self.args.timeout)
        except Exception:
            hint = ""
            if lt.IN_DOCKER and (urlparse(self.url).hostname or "") in ("localhost", "127.0.0.1", "::1"):
                hint = (" Hinweis: Im Docker-Container ist „localhost“ der Container selbst – für eine "
                        "API auf diesem Rechner host.docker.internal statt localhost eintragen.")
            raise lt.PreflightError(f"API unter {self.url} nicht erreichbar.{hint}") from None
        if not status_ok(status, self.args.expect_status):
            raise lt.PreflightError(f"Die API antwortet mit Status {status}, erwartet wird "
                                    f"{self.args.expect_status} – bitte Adresse, Methode, Kopfzeilen und "
                                    "Body prüfen.")
        return {"status": status, "bytes": size, "assets": 0, "final_url": self.url,
                "total_bytes": size, "files": [], "rtt_ms": (t_first - t0) * 1000, "busy": None}

    async def _view(self, r, t0):
        status, size, t_first = await self._call()
        r["ttft"], r["tp_first"], r["status"] = t_first - t0, t_first, status
        r["bytes"], r["requests"] = size, 1
        if status_ok(status, self.args.expect_status):
            r["ok"] = True
        else:
            r["error"] = f"http_{status}"


# ════════════════════════════════════════════════════════════════════════════
#  Kennzahlen
# ════════════════════════════════════════════════════════════════════════════

def summarize(results, wall):
    ok = [r for r in results if r["ok"]]
    n = len(results)
    ttfbs = [r["ttft"] for r in ok]
    loads = [r["e2e"] for r in ok]
    size = sum(r.get("bytes") or 0 for r in ok)
    return {
        "n": n, "ok": len(ok), "errors": n - len(ok),
        "error_rate": (n - len(ok)) / n if n else 0.0,
        "error_types": dict(Counter(r["error"] for r in results if not r["ok"])),
        "wall_s": wall,
        "ttft_p50": pct(ttfbs, 50), "ttft_p95": pct(ttfbs, 95),
        "ttft_max": max(ttfbs) if ttfbs else None,
        "e2e_p50": pct(loads, 50), "e2e_p95": pct(loads, 95), "e2e_mean": mean(loads),
        "e2e_max": max(loads) if loads else None,
        "req_s": len(ok) / wall if wall else None,           # Seitenaufrufe pro Sekunde
        "bytes_s": size / wall if wall else None,
        "bytes_avg": size / len(ok) if ok else None,
        "files_avg": mean([r.get("requests") for r in ok]),
        # Gibt es bei Websites nicht – die Felder bleiben, damit die Form zum KI-Test passt
        "out_tps": None, "user_tps_p50": None,
    }


def summarize_window(results, w0, w1, c, slo_load):
    """Kennzahlen aus dem eingeschwungenen Messfenster [w0, w1)."""
    length = max(1e-6, w1 - w0)
    inwin = [r for r in results if w0 <= r["tp_start"] < w1]
    s = summarize(inwin, length)
    done = [r for r in results if r["ok"] and w0 <= r["tp_start"] + r["e2e"] < w1]
    s["req_s"] = len(done) / length
    good = [r for r in inwin if r["ok"] and r["e2e"] <= slo_load]
    s["goodput_pct"] = len(good) / len(inwin) * 100 if inwin else None
    s.update(window_s=length, n_window=len(inwin), concurrency=c)
    return s


def meets_slo(s, cfg):
    """Ziel erreicht: keine Fehler, und 95 % der Besucher haben die Seite rechtzeitig."""
    return (s.get("error_rate") == 0 and s.get("e2e_p95") is not None
            and s["e2e_p95"] <= cfg.get("slo_load", DEFAULTS["slo_load"]))


def capacity(summary):
    """Für wie viele Besucher gleichzeitig reicht es? Ein Besucher ruft alle
    (Ladezeit + Pause) Sekunden eine Seite auf (Gesetz von Little).
    Bei einer API steht in „users“ stattdessen, wie viele Anfragen pro Minute flüssig durchgehen."""
    cfg = summary.get("config") or {}
    api = cfg.get("kind") == "api"
    think = cfg.get("think_time", DEFAULTS["think_time"])
    out = {"think_time": think}
    best = None
    for s in sorted((summary.get("ramp") or {}).get("steps", []), key=lambda x: x["concurrency"]):
        if meets_slo(s, cfg):
            best = s
    if best:
        out["rec_concurrency"] = best["concurrency"]
        out["users_ramp"] = ((best.get("req_s") or 0) * 60 or None) if api else lt.users_for(
            best.get("req_s"), best.get("e2e_mean"), think)
    good = [s for s in (summary.get("rate") or {}).get("stages", [])
            if meets_slo(s, cfg) and not s.get("overloaded")]
    if good:
        g = max(good, key=lambda s: s["rate"])
        out["rate_ok"] = g["rate"]
        out["users_rate"] = ((g.get("rate_actual") or g["rate"]) * 60) if api else lt.users_for(
            g.get("rate_actual") or g["rate"], g.get("e2e_mean"), think)
    out["users"] = out.get("users_rate") or out.get("users_ramp")
    out["source"] = "rate" if out.get("users_rate") else "ramp" if out.get("users_ramp") else None
    return out


def lt_mins(m):
    """'1 Minute', '3 Minuten', '0,5 Minuten'."""
    m = float(m)
    return fmt(m, 0 if m == int(m) else 1) + (" Minute" if m == 1 else " Minuten")


def verdict(summary):
    """Empfehlung in einem Satz: good | warn | bad plus Begründungen."""
    cfg = summary.get("config") or {}
    w, api = words(cfg), cfg.get("kind") == "api"
    users, target = capacity(summary).get("users"), cfg.get("target_users") or 0
    rank = {"good": 0, "warn": 1, "bad": 2}
    st, reasons = "good", []

    def note(status, text):
        nonlocal st
        if rank[status] > rank[st]:
            st = status
        reasons.append((status, text))

    def n(v):
        return fmt(lt.round_users(v), 0)

    tested = (summary.get("ramp") or {}).get("steps") or (summary.get("rate") or {}).get("stages")
    if api:
        have, what = "Schafft", "Anfragen pro Minute"
        too_slow = "Schon bei wenigen gleichzeitigen Anfragen antwortet die API langsamer als gewünscht."
    else:
        have, what = "Reicht für", f"{w['units']} gleichzeitig"
        too_slow = f"Schon bei wenigen {w['units']}n ist {w['subj']} langsamer als gewünscht."
    if tested:
        if not users:
            note("bad", too_slow)
        elif target:
            if users >= target:
                note("good", f"{have} ≈ {n(users)} {what} – erwartet werden {fmt(target, 0)}.")
            elif users >= 0.7 * target:
                note("warn", f"Knapp: {have.lower()} ≈ {n(users)} {what}, erwartet werden {fmt(target, 0)}.")
            else:
                note("bad", f"{have} nur ≈ {n(users)} {what}, erwartet werden {fmt(target, 0)}.")
        else:
            note("good", f"{have} ≈ {n(users)} {what}.")
    spike = summary.get("spike")
    if spike:
        if spike.get("crashed"):
            note("bad", f"Beim großen Ansturm war {w['subj']} nicht mehr erreichbar.")
        elif spike["burst"]["error_rate"] > 0:
            note("warn", f"Beim großen Ansturm bekamen {fmt(spike['burst']['error_rate'] * 100, 0)} % "
                         f"der {w['units']} {w['fail']}.")
        elif spike.get("recovered") is False:
            note("warn", f"Nach dem großen Ansturm blieb {w['subj']} langsamer als vorher.")
        else:
            note("good", f"Den großen Ansturm ({spike['size']} {w['units']} im selben Augenblick) hat sie "
                         "ohne Fehler überstanden.")
    deg = (summary.get("soak") or {}).get("degradation") or {}
    soak = summary.get("soak")
    if soak and soak["total"]["error_rate"] > 0:
        note("warn", f"Unter Dauerlast gab es Fehler ({fmt(soak['total']['error_rate'] * 100, 1)} % der {w['events']}).")
    elif deg.get("ttft_change_pct") is not None and deg["ttft_change_pct"] > 25:
        note("warn", f"Unter Dauerlast wird {w['subj']} langsamer (+{fmt(deg['ttft_change_pct'], 0)} % {w['time']}).")
    elif soak:
        note("good", f"Unter Dauerlast ({lt_mins(soak['minutes'])}) bleibt {w['subj']} gleich schnell.")
    if (summary.get("quality") or {}).get("overall") == "niedrig":
        note("warn", "Die Messung selbst war nicht ganz sauber – Test wiederholen, bevor entschieden wird.")
    headline = {"good": f"{w['subject']} hält {w['stand']} stand.",
                "warn": f"{w['subject']} hält stand – mit Einschränkungen.",
                "bad": f"{w['subject']} ist {w['stand']} so nicht gewachsen."}[st]
    if not tested:
        headline, st = "Für ein Urteil fehlen die Lasttests.", "warn"
    return {"status": st, "headline": headline, "reasons": reasons}


# ════════════════════════════════════════════════════════════════════════════
#  Wie sehr kann man den Zahlen trauen?
# ════════════════════════════════════════════════════════════════════════════

def assess_quality(summary):
    """Prüft die Messung selbst – gleiche Idee und gleiche Grenzwerte wie beim KI-Server-Test.
    Jeder Punkt: Ampel (good/warn/bad), kurzer Titel, Messwert und eine Erklärung."""
    items = []
    w = words(summary.get("config"))
    steps = (summary.get("ramp") or {}).get("steps", [])
    stages = (summary.get("rate") or {}).get("stages", [])

    def add(status, title, value, text):
        items.append({"status": status, "title": title, "value": value, "text": text})

    lags = [(f"{s['concurrency']} gleichzeitig", s["client_lag_ms"]) for s in steps
            if s.get("client_lag_ms") is not None]
    lags += [(f"{fmt(s['rate'] * 60, 0)} {w['events']}/min", s["client_lag_ms"]) for s in stages
             if s.get("client_lag_ms") is not None]
    if lags:
        where, worst = max(lags, key=lambda x: x[1])
        if worst < 30:
            add("good", "Kam der Messrechner hinterher?", f"ja (max. {fmt(worst, 0)} ms Verzug)",
                f"Der Rechner, der die {w['units']} spielt, war nie überlastet. Er misst also sauber.")
        elif worst < 150:
            add("warn", "Kam der Messrechner hinterher?", f"knapp ({fmt(worst, 0)} ms bei {where})",
                f"Bei vielen gleichzeitigen {w['units']}n hatte der Messrechner viel zu tun. Die {w['time']}en "
                "auf den höchsten Stufen könnten etwas zu hoch sein.")
        else:
            add("bad", "Kam der Messrechner hinterher?", f"nein ({fmt(worst, 0)} ms bei {where})",
                "Der Messrechner war überlastet. Die Werte auf den höchsten Stufen sind zu schlecht – "
                f"{w['subj']} kann mehr. Besser von einem stärkeren Rechner testen.")

    lates = [s["send_late_ms"] for s in stages if s.get("send_late_ms") is not None]
    if lates:
        worst = max(lates)
        st = "good" if worst < 50 else "warn" if worst < 250 else "bad"
        add(st, f"Kamen die zufälligen {w['units']} pünktlich?", f"max. {fmt(worst, 0)} ms zu spät",
            {"good": "Beim Test „Echter Andrang“ ging jeder Aufruf zum geplanten Zeitpunkt los.",
             "warn": "Einige Aufrufe gingen etwas verspätet los. Die tatsächliche Menge pro Minute war "
                     "dadurch leicht kleiner als geplant.",
             "bad": "Der Messrechner kam mit dem Losschicken nicht hinterher. Die Ergebnisse von "
                    "„Echter Andrang“ sind zu gut – besser von einem stärkeren Rechner testen."}[st])

    counts = [s["n_window"] for s in steps if s.get("n_window") is not None]
    if counts:
        fewest = min(counts)
        if fewest >= 20:
            add("good", "Genug Messungen je Stufe?", f"ja (mindestens {fewest})",
                "Jede Stufe beruht auf genug Seitenaufrufen, damit einzelne Ausreißer nicht das Bild bestimmen.")
        else:
            add("warn", "Genug Messungen je Stufe?", f"wenig (nur {fewest} auf einer Stufe)",
                "Mindestens eine Stufe beruht auf wenigen Seitenaufrufen. Einzelne langsame Aufrufe "
                "wiegen dort schwer – längere Stufen wählen (Profil „Gründlich“).")

    sts = [i["status"] for i in items]
    overall = "niedrig" if "bad" in sts else "mittel" if sts.count("warn") >= 2 else "hoch"
    return {"overall": overall, "items": items}


# ════════════════════════════════════════════════════════════════════════════
#  Die einzelnen Tests
# ════════════════════════════════════════════════════════════════════════════

class WebStressTest:
    """Gleiche Schnittstelle wie llm_stresstest.StressTest (summary, mon, on_update, run)."""

    def __init__(self, args, outdir):
        self.a = args
        self.outdir = outdir
        self.raw = open(os.path.join(outdir, "raw_requests.jsonl"), "w", encoding="utf-8")
        if args.seed is None:
            args.seed = random.randrange(1, 2 ** 31)
        self.arrivals = random.Random(args.seed + 1)
        # Kopfzeilen-Werte und Body enthalten oft Zugangsdaten – ins Ergebnis kommen nur Namen und Größe.
        config = {k: v for k, v in vars(args).items() if k not in ("headers", "body")}
        if args.kind == "api":
            config["header_names"] = sorted(args.headers)
            config["body_bytes"] = len(args.body.encode("utf-8"))
        self.summary = {"meta": {"local_monitor": False}, "config": config}
        self.w = words(config)
        self.mon = lt.Monitor(args.monitor_interval, None, local=False)
        self.server_down = False
        self.on_update = None
        self.lags = []         # (Zeitpunkt, Verzögerung in s) der eigenen Ereignisschleife

    # ── Aufpasser: kommt der Messrechner selbst hinterher? ─────────────────
    async def lag_watch(self):
        """Misst, wie verspätet ein 100-ms-Wecker klingelt. Ist der Messrechner mit dem Laden der
        Seiten überlastet, kommt der Wecker zu spät – dann wären auch die gemessenen Ladezeiten
        zu hoch, und der Bericht würde es zu Unrecht der Website anlasten."""
        while True:
            t = time.perf_counter()
            await asyncio.sleep(0.1)
            self.lags.append((t, max(0.0, time.perf_counter() - t - 0.1)))
            if len(self.lags) > 200000:
                del self.lags[:50000]

    def lag_ms(self, a, b):
        v = pct([lag for t, lag in self.lags if a <= t < b], 95)
        return v * 1000 if v is not None else None

    @staticmethod
    def job():
        return None, 0

    def save_raw(self, test, results, **extra):
        keys = ("ok", "t_start", "ttft", "e2e", "bytes", "requests", "status", "error", "error_detail")
        for r in results:
            self.raw.write(json.dumps({"test": test, **extra, **{k: r.get(k) for k in keys}}) + "\n")
        self.raw.flush()

    def derive(self):
        self.summary["capacity"] = capacity(self.summary)
        self.summary["probes"] = None          # Kontrollfragen gibt es nur beim KI-Server
        self.summary["economics"] = None       # Kostenvergleich ebenso
        self.summary["verdict"] = verdict(self.summary)

    def notify(self):
        self.derive()
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                pass

    def save_summary(self):
        self.summary["monitor"] = self.mon.samples
        self.derive()
        with open(os.path.join(self.outdir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(self.summary, f, indent=1, default=str)
        self.notify()

    async def preflight(self, client):
        log(f"Vorbereitung: {self.w['subject'].split()[1]} erreichbar?")
        self.summary["meta"].update({"started": dt.datetime.now().isoformat(timespec="seconds"),
                                     "host": platform.node(), "version": lt.VERSION,
                                     "server_host": urlparse(self.a.base_url).hostname})
        info = await client.prepare()
        self.summary["prechecks"] = info
        log(f"  Erreichbar · erste Antwort nach {fmt(info['rtt_ms'], 0)} ms"
            + (f" · {info['assets']} Dateien gehören zur Seite" if self.a.kind == "web"
               else f" · {self.a.method} {urlparse(self.a.base_url).path or '/'} → Status {info['status']}"))
        if info["final_url"].rstrip("/") != self.a.base_url.rstrip("/"):
            log(f"  Weitergeleitet nach {info['final_url']}")
        self.notify()

    async def _alone(self, client, label, n):
        self.mon.phase = label
        res, wall = await lt.run_batch(client, self.job, n, 1)
        self.save_raw(label, res)
        return summarize(res, wall)

    async def baseline(self, client):
        log("━━ 1/5 Einer allein ━━")
        s = await self._alone(client, "baseline", self.a.baseline_requests)
        self.summary["baseline"] = s
        log(f"  Erste Antwort {fmt(s['ttft_p50'], 3)}s · {self.w['time']} {fmt(s['e2e_p50'], 2)}s "
            f"· Fehler {s['errors']}")

    def _break_reason(self, s):
        if s["ok"] == 0:
            return "keine Antwort mehr"
        if s["error_rate"] > self.a.max_error_rate:
            return f"zu viele Fehler: {s['error_rate'] * 100:.0f} %"
        if s["e2e_p95"] and s["e2e_p95"] > self.a.break_load:
            return f"Ladezeit über {self.a.break_load:.0f} s"
        return None

    async def ramp(self, client):
        log("━━ 2/5 Immer mehr gleichzeitig ━━")
        a = self.a
        steps, brk = [], None

        def publish():
            self.summary["ramp"] = {"steps": steps, "break": brk, "saturated": None}
            self.notify()

        for c in sorted({int(x) for x in a.levels.split(",") if x.strip()}):
            self.mon.phase = f"ramp_c{c}"
            log(f"  {c:>4} gleichzeitig: {a.level_seconds:.0f}s messen …")
            res, w0, w1 = await lt.run_timed(client, self.job, c, a.level_seconds, a.warmup_seconds,
                                             a.min_samples, a.level_seconds * 4)
            s = summarize_window(res, w0, w1, c, a.slo_load)
            s["fine"] = False
            s["client_lag_ms"] = self.lag_ms(w0, w1)
            self.save_raw("ramp", res, level=c)
            steps.append(s)
            log(f"      → {fmt(s['req_s'], 1)} Seiten/s · Ladezeit p95 {fmt(s['e2e_p95'], 2)}s · "
                f"erste Antwort p95 {fmt(s['ttft_p95'], 2)}s · Fehler {s['error_rate'] * 100:.0f}% · "
                f"{s['n_window']} Messungen")
            reason = self._break_reason(s)
            if reason:
                brk = {"concurrency": c, "reason": reason}
                log(f"  ✗ Grenze erreicht: {reason}")
            publish()
            if reason:
                break
        publish()

    def _rates(self):
        """Ankunftsraten in Aufrufen pro Sekunde: Anteile dessen, was der Stufentest geschafft hat."""
        steps = (self.summary.get("ramp") or {}).get("steps") or []
        cfg = self.summary["config"]
        good = [s["req_s"] for s in steps if meets_slo(s, cfg) and s.get("req_s")]
        top = max(good, default=0) or max((s.get("req_s") or 0 for s in steps), default=0)
        if not top:
            base = self.summary.get("baseline") or {}
            top = 1 / base["e2e_p50"] if base.get("e2e_p50") else 0
        return sorted({round(top * f, 3) for f in (0.5, 0.8, 1.0, 1.2)} - {0})

    async def rate_test(self, client):
        log(f"━━ 3/5 Echter Andrang ({self.w['units']} kommen zufällig) ━━")
        a = self.a
        rates = self._rates()
        if not rates:
            log("  Übersprungen – erst muss der Stufentest laufen.")
            return
        drain = min(a.timeout, max(10.0, a.rate_seconds))
        stages, brk = [], None

        def publish():
            self.summary["rate"] = {"stages": stages, "break": brk, "think_time": a.think_time}
            self.notify()

        for rate in rates:
            self.mon.phase = f"rate_{rate * 60:g}"
            log(f"  {fmt(rate * 60, 0)} Aufrufe pro Minute (zufällig verteilt): {a.rate_seconds:.0f}s …")
            res, w0, w1, max_in, late = await lt.run_rate(client, self.job, rate, a.rate_seconds,
                                                          a.warmup_seconds, drain, self.arrivals)
            s = summarize_window(res, w0, w1, None, a.slo_load)
            inwin = sorted((r for r in res if w0 <= r["tp_start"] < w1), key=lambda r: r["tp_start"])
            s.update(rate=rate, rate_actual=len(inwin) / max(1e-6, w1 - w0), max_inflight=max_in,
                     send_late_ms=late * 1000 if late is not None else None,
                     client_lag_ms=self.lag_ms(w0, w1))
            # Wächst die Schlange? Ladezeit der letzten gegen die ersten Besucher
            ok = [r for r in inwin if r["ok"]]
            k = len(ok) // 3
            if k >= 3:
                first, last = pct([r["e2e"] for r in ok[:k]], 50), pct([r["e2e"] for r in ok[-k:]], 50)
                s["queue_growth"] = last / first if first else None
                s["overloaded"] = bool(s["queue_growth"] and s["queue_growth"] > 2 and last > a.slo_load)
            else:
                s["overloaded"] = s["error_rate"] > a.max_error_rate
            self.save_raw("rate", res, rate=rate)
            stages.append(s)
            log(f"      → Ladezeit p50 {fmt(s['e2e_p50'], 2)}s / p95 {fmt(s['e2e_p95'], 2)}s · "
                f"bis zu {max_in} gleichzeitig" + (" · Schlange wächst" if s["overloaded"] else ""))
            reason = self._break_reason(s) or (
                "die Warteschlange wächst immer weiter" if s["overloaded"] else None)
            if reason:
                brk = {"rate": rate, "reason": reason}
                log(f"  ✗ Überlastet: {reason}")
            publish()
            if reason:
                break
        publish()

    async def spike(self, client):
        log("━━ 4/5 Großer Ansturm ━━")
        n = self.a.spike_size
        self.mon.phase = "spike_idle"
        await asyncio.sleep(self.a.spike_idle)
        self.mon.phase = "spike"
        log(f"  {n} {self.w['units']} auf einmal …")
        t0 = time.perf_counter()
        res, wall = await lt.run_batch(client, self.job, n, n)
        s = summarize(res, wall)
        s["client_lag_ms"] = self.lag_ms(t0, t0 + wall)
        self.save_raw("spike", res)
        log(f"  → bedient {s['ok']}/{n} · längste Ladezeit {fmt(s['e2e_max'], 1)}s")
        await asyncio.sleep(min(3, self.a.spike_idle))
        rec = await self._alone(client, "spike_recovery", 3)
        crashed = rec["ok"] == 0
        self.server_down = crashed
        base = self.summary.get("baseline") or {}
        recovered = None
        if rec["ok"] and base.get("e2e_p50"):
            recovered = rec["e2e_p50"] <= base["e2e_p50"] * 1.5 + 0.05
        elif rec["ok"]:
            recovered = True
        log(f"  Danach wieder normal: {'ja' if recovered else 'nein/unklar'}")
        self.summary["spike"] = {"size": n, "burst": s, "recovery": rec, "recovered": recovered,
                                 "crashed": crashed}

    async def soak(self, client):
        minutes = self.a.soak_minutes
        c = max(1, capacity(self.summary).get("rec_concurrency") or 4)
        log(f"━━ 5/5 Ausdauer: {fmt(float(minutes), 1)} min bei {c} gleichzeitig ━━")
        self.mon.phase = "soak"
        seconds = minutes * 60
        res, w0, w1 = await lt.run_timed(client, self.job, c, seconds, 0, 1, seconds)
        s = summarize(res, max(1e-6, w1 - w0))
        self.save_raw("soak", res)
        deg = None
        ok = sorted((r for r in res if r["ok"]), key=lambda r: r["tp_start"])
        k = len(ok) // 3
        if k >= 3:
            first, last = ok[:k], ok[-k:]
            span = lambda part: max(1e-6, part[-1]["tp_start"] - part[0]["tp_start"])  # noqa: E731
            f_rate, l_rate = k / span(first), k / span(last)
            f_load, l_load = pct([r["e2e"] for r in first], 50), pct([r["e2e"] for r in last], 50)
            deg = {"tps_change_pct": (l_rate / f_rate - 1) * 100 if f_rate else None,
                   "ttft_change_pct": (l_load / f_load - 1) * 100 if f_load else None}
            log(f"  Ladezeit Anfang → Ende: {fmt(deg['ttft_change_pct'], 1)} %")
        # Zeitverlauf in gleich langen Abschnitten (für das Diagramm im Bericht)
        buckets, nb = [], max(3, min(12, int(seconds // 15)))
        span_s = max(1e-6, w1 - w0) / nb
        for i in range(nb):
            part = [r for r in res if w0 + i * span_s <= r["tp_start"] < w0 + (i + 1) * span_s]
            buckets.append({"t_min": (i + 1) * span_s / 60, "s": summarize(part, span_s) if part else None})
        self.summary["soak"] = {"minutes": minutes, "concurrency": c, "total": s, "buckets": buckets,
                                "degradation": deg}

    async def control(self, client):
        base = self.summary.get("baseline")
        if not base:
            return
        log("━━ Kontrollmessung: noch einmal wie am Anfang ━━")
        await asyncio.sleep(min(3, self.a.cooldown))
        s = await self._alone(client, "control", self.a.baseline_requests)
        b, c = base.get("e2e_p50"), s.get("e2e_p50")
        # Tempo = Kehrwert der Ladezeit: −20 % heißt „ein Fünftel langsamer als am Anfang“
        self.summary["control"] = {"s": s,
                                   "tps_diff_pct": (b / c - 1) * 100 if b and c else None,
                                   "ttft_diff_pct": (c / b - 1) * 100 if b and c else None}
        log(f"  {self.w['time']} {fmt(c, 2)}s (Anfang: {fmt(b, 2)}s)")

    def make_client(self):
        return (ApiClient if self.a.kind == "api" else WebClient)(self.a)

    async def run(self):
        self.mon.start()
        lag_task = asyncio.create_task(self.lag_watch())
        tests = [t.strip() for t in self.a.tests.split(",")]
        try:
            async with self.make_client() as client:
                await self.preflight(client)
                plan = [("baseline", self.baseline), ("ramp", self.ramp), ("rate", self.rate_test),
                        ("spike", self.spike), ("soak", self.soak), ("control", self.control)]
                for name, fn in plan:
                    if name != "control" and name not in tests:
                        continue
                    if name == "soak" and self.a.soak_minutes <= 0:
                        continue
                    if name == "control" and "baseline" not in tests:
                        continue
                    if self.server_down:
                        self.summary.setdefault("skipped", []).append(name)
                        continue
                    self.summary["meta"]["current_test"] = name
                    self.notify()
                    await fn(client)
                    self.save_summary()
                    self.mon.phase = "idle"
                    await asyncio.sleep(self.a.cooldown)
        except KeyboardInterrupt:
            log("Abgebrochen – erstelle Bericht mit bisherigen Daten.")
        finally:
            lag_task.cancel()
            self.summary["meta"]["current_test"] = None
            self.summary["meta"]["finished"] = dt.datetime.now().isoformat(timespec="seconds")
            self.mon.stop()
            self.mon.join(timeout=5)
            self.summary["quality"] = assess_quality(self.summary)
            self.save_summary()
            self.raw.close()
