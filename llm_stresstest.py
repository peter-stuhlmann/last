#!/usr/bin/env python3
"""
LLM-Härtetest für OpenAI-kompatible Server (vLLM, SGLang, llama.cpp, Ollama, TGI …)
===================================================================================

Führt eine komplette Testreihe durch und erzeugt daraus eine PowerPoint-Präsentation:

  1. Baseline          – einzelne Anfragen, Bestwerte ohne Last
  2. Concurrency-Ramp  – 1, 2, 4, 8 … parallele Nutzer bis zum Bruchpunkt
  3. Offene Last       – zufällige Ankünfte (Poisson) mit fester Rate, wie im Alltag
  4. Kontext-Sweep     – wachsende Eingabelängen bis zum Kontext-/Speicherlimit
  5. Spike-Test        – plötzlicher Ansturm, danach Erholungsprüfung
  6. Soak-Test         – Dauerlast über längere Zeit (Drosselung, Leaks)

Parallel werden GPU/Speicher (nvidia-smi, /proc/meminfo) und – falls vorhanden –
die Prometheus-Metriken des Servers (KV-Cache, Warteschlange, Verdrängungen,
Prefix-Cache) aufgezeichnet. Aus Durchsatz und Antwortdauer wird über das Gesetz von
Little abgeschätzt, für wie viele aktive Nutzer der Server reicht.

Installation:
    pip install aiohttp python-pptx reportlab

Beispiele:
    python3 llm_stresstest.py --base-url http://localhost:8000/v1 --model Qwen/Qwen3-32B
    python3 llm_stresstest.py --base-url http://localhost:11434/v1 --model qwen3:32b --quick
    python3 llm_stresstest.py --report-only results_20260929_1730   # nur Präsentation neu bauen

Tipp: Das Skript direkt auf dem Spark laufen lassen, dann stimmen die System-Metriken.
"""

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import math
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from urllib.parse import urlparse

# Windows-Konsolen können sonst an Sonderzeichen (✓, ━, →) scheitern
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# Im Docker-Container (siehe Dockerfile): Standardadresse und Ergebnisordner per Umgebung
IN_DOCKER = os.environ.get("LLMST_IN_DOCKER") == "1"
RESULTS_ROOT = os.environ.get("LLMST_RESULTS", ".")


def read_version():
    """Versionsnummer aus der Datei VERSION neben diesem Skript – steht in jeder summary.json,
    damit auch Jahre später klar ist, womit gemessen wurde."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


VERSION = read_version()
USER_AGENT = "LAST-Lasttest/1.0 (Lasttest des eigenen KI-Servers)"  # der Test gibt sich zu erkennen


def is_local_url(url):
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host == platform.node().lower()

try:
    import aiohttp
except ImportError:
    exe = sys.executable if " " not in sys.executable else f'"{sys.executable}"'
    sys.exit("Es fehlen Python-Pakete für genau dieses Python (" + sys.executable + ").\n"
             "Installieren mit:\n    " + exe + " -m pip install aiohttp python-pptx reportlab")


# ════════════════════════════════════════════════════════════════════════════
#  Hilfsfunktionen
# ════════════════════════════════════════════════════════════════════════════

def pct(values, p):
    """Perzentil mit linearer Interpolation; None bei leerer Liste."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def mean(values):
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


LOG_SINKS = []  # zusätzliche Empfänger für Log-Zeilen (z. B. die Weboberfläche)


class PreflightError(Exception):
    """Server nicht erreichbar oder Testanfrage fehlgeschlagen."""


def log(msg=""):
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    for sink in LOG_SINKS:
        try:
            sink(line)
        except Exception:
            pass


def fmt(v, digits=2, unit=""):
    if v is None:
        return "–"
    if isinstance(v, float):
        s = f"{v:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        s = f"{v:,}".replace(",", ".")
    return f"{s}{unit}"


WORDS = ("system daten modell server anfrage antwort netzwerk speicher grafik "
         "rechenleistung energie wetter berg fluss stadt wald garten musik "
         "geschichte wissenschaft sprache computer algorithmus struktur zukunft "
         "vergangenheit analyse bericht projekt team kunde markt produkt qualität "
         "sicherheit prozess methode ergebnis frage idee lösung problem strategie "
         "ocean mountain river forest valley engine signal memory kernel matrix "
         "vector tensor gradient network cluster packet stream buffer latency "
         "throughput window context token layer neuron weight bias training "
         "inference benchmark hardware software compiler library function object "
         "license history culture economy politics climate energy transport "
         "medicine biology chemistry physics astronomy geology literature art").split()


class PromptFactory:
    """Erzeugt Chat-Nachrichten mit gewünschter Token-Länge. Jede Nachricht beginnt mit
    einem zufälligen Kennzeichen, damit Prefix-Caching die Messung nicht verfälscht.
    Mit shared_prefix > 0 und shared=True steht davor ein System-Prompt, der bei allen
    Anfragen gleich ist – wie im echten Betrieb (gleiche Anweisungen, gleicher RAG-Kontext).
    Mit seed sind die erzeugten Texte wiederholbar."""

    def __init__(self, tokens_per_word=1.35, seed=None, shared_prefix=0):
        self.tpw = tokens_per_word
        self.rnd = random.Random(seed)
        self.shared_prefix = shared_prefix
        self._prefix = None

    def _filler(self, tokens, rnd):
        n_words = max(1, int(tokens / self.tpw))
        return " ".join(rnd.choice(WORDS) for _ in range(n_words))

    def prefix(self):
        if self._prefix is None:  # erst bei Bedarf bauen – dann ist tpw schon kalibriert
            self._prefix = ("Du bist ein hilfreicher Assistent. Hintergrundwissen: "
                            + self._filler(max(1, self.shared_prefix - 20), random.Random(12345)))
        return self._prefix

    def make(self, input_tokens, shared=False):
        instruction = ("\n\nFasse den obigen Text kurz zusammen und schreibe danach eine "
                       "sehr lange, ausführliche Geschichte über einen Leuchtturmwärter.")
        overhead = 40
        msgs = []
        if shared and self.shared_prefix > 0:
            msgs.append({"role": "system", "content": self.prefix()})
            input_tokens -= self.shared_prefix
        tag = f"{self.rnd.getrandbits(128):032x}"
        filler = self._filler(max(1, input_tokens - overhead), self.rnd)
        msgs.append({"role": "user", "content": f"[{tag}] Text: {filler}{instruction}"})
        return msgs


# ════════════════════════════════════════════════════════════════════════════
#  System- und Server-Monitoring (Hintergrund-Thread)
# ════════════════════════════════════════════════════════════════════════════

SERVER_METRICS = {
    # vLLM
    "vllm:gpu_cache_usage_perc": "kv", "vllm:kv_cache_usage_perc": "kv",
    "vllm:num_requests_running": "running", "vllm:num_requests_waiting": "waiting",
    # SGLang
    "sglang:token_usage": "kv", "sglang:num_running_reqs": "running",
    "sglang:num_queue_reqs": "waiting",
    # llama.cpp (--metrics)
    "llamacpp:kv_cache_usage_ratio": "kv", "llamacpp:requests_processing": "running",
    "llamacpp:requests_deferred": "waiting",
    # Verdrängungen (KV-Cache voll) und Prefix-Cache – Zähler, ausgewertet als Differenz
    "vllm:num_preemptions_total": "preempt_total",
    "vllm:prefix_cache_queries_total": "pc_queries", "vllm:prefix_cache_hits_total": "pc_hits",
    "vllm:gpu_prefix_cache_hit_rate": "pc_rate", "sglang:cache_hit_rate": "pc_rate",
}
# Quoten werden über mehrere Engines/Alias-Namen gemittelt, Zähler und Anzahlen summiert
MEAN_METRICS = {"kv", "pc_rate"}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


class Monitor(threading.Thread):
    def __init__(self, interval, metrics_url, local=True):
        super().__init__(daemon=True)
        self.local = local
        self.interval = interval
        self.metrics_url = metrics_url
        self.samples = []
        self.phase = "idle"
        self.t0 = time.time()
        self._stop_ev = threading.Event()
        self.has_gpu = local and shutil.which("nvidia-smi") is not None
        self.has_metrics = None  # wird beim ersten Versuch bestimmt
        self.gpu_name = None
        if self.has_gpu:
            try:
                self.gpu_name = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
            except Exception:
                pass

    def stop(self):
        self._stop_ev.set()

    def _gpu(self):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,clocks.sm,"
                 "power.draw,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
            u, t, c, p, m = [_num(x.strip()) for x in out.split(",")]
            return {"gpu_util": u, "gpu_temp": t, "gpu_clock": c, "gpu_power": p,
                    "gpu_mem_mb": m}
        except Exception:
            return {}

    @staticmethod
    def _mem():
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    info[k] = int(v.split()[0])
            total = info["MemTotal"] / 1048576
            avail = info["MemAvailable"] / 1048576
            return {"ram_used_gb": total - avail, "ram_total_gb": total}
        except Exception:
            return {}

    def _server(self):
        if not self.metrics_url or self.has_metrics is False:
            return {}
        try:
            with urllib.request.urlopen(self.metrics_url, timeout=3) as r:
                text = r.read().decode("utf-8", "replace")
            vals = {}
            for line in text.splitlines():
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([a-zA-Z_:][\w:]*)(\{[^}]*\})?\s+([-\d.eE+naNInf]+)", line)
                if m and m.group(1) in SERVER_METRICS:
                    v = _num(m.group(3))
                    if v is not None and not math.isnan(v):
                        vals.setdefault(SERVER_METRICS[m.group(1)], []).append(v)
            res = {k: statistics.fmean(v) if k in MEAN_METRICS else sum(v)
                   for k, v in vals.items()}
            if self.has_metrics is None:
                self.has_metrics = bool(res)
            for k in MEAN_METRICS:
                if k in res and res[k] <= 1.0:
                    res[k] *= 100.0  # in Prozent
            return res
        except Exception:
            if self.has_metrics is None:
                self.has_metrics = False
            return {}

    def run(self):
        while not self._stop_ev.is_set():
            s = {"t": round(time.time() - self.t0, 2), "phase": self.phase}
            if self.has_gpu:
                s.update(self._gpu())
            if self.local:
                s.update(self._mem())
            s.update(self._server())
            self.samples.append(s)
            self._stop_ev.wait(self.interval)


# ════════════════════════════════════════════════════════════════════════════
#  Lastgenerator
# ════════════════════════════════════════════════════════════════════════════

class Client:
    def __init__(self, args):
        self.args = args
        self.url = args.base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if args.api_key:
            self.headers["Authorization"] = f"Bearer {args.api_key}"
        self.use_ignore_eos = not args.no_ignore_eos
        self.session = None

    async def __aenter__(self):
        conn = aiohttp.TCPConnector(limit=0, force_close=False)
        self.session = aiohttp.ClientSession(connector=conn, headers=self.headers)
        return self

    async def __aexit__(self, *exc):
        await self.session.close()

    def payload(self, messages, max_tokens, probe=False):
        p = {
            "model": self.args.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0 if probe else 0.7,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.use_ignore_eos and not probe:
            p["ignore_eos"] = True          # vLLM/SGLang: feste Ausgabelänge
            p["min_tokens"] = max_tokens
        if self.args.disable_thinking:
            p["chat_template_kwargs"] = {"enable_thinking": False}
        return p

    @staticmethod
    def blank_result(t0=None):
        t0 = time.perf_counter() if t0 is None else t0
        return {"ok": False, "t_start": time.time(), "tp_start": t0, "tp_first": None,
                "tp_last": None, "ttft": None, "ttfc": None, "e2e": None, "out_tokens": 0,
                "in_tokens": None, "itl": None, "max_gap": None, "error": None, "status": None,
                "usage": False, "reasoning": False}

    async def request(self, messages, max_tokens, timeout=None, probe=False):
        """Eine Streaming-Anfrage. Liefert ein Ergebnis-Dict mit Zeitmessungen.
        tp_start / tp_first / tp_last sind perf_counter-Zeitpunkte (Start, erstes und
        letztes Textstück) – damit lässt sich die Leistung in beliebigen Zeitfenstern
        berechnen, ohne jede einzelne Token-Zeit zu speichern.
        ttfc = Zeit bis zum ersten Antwort-Token nach dem Nachdenken (nur Thinking-Modelle),
        max_gap = längste Pause zwischen zwei Textstücken (Ruckeln).
        probe=True: Kontrollfrage – Temperatur 0, natürliche Länge, Antworttext in r["text"]."""
        timeout = timeout or self.args.timeout
        t0 = time.perf_counter()
        r = self.blank_result(t0)
        n_chunks, usage, parts = 0, None, []
        try:
            async with self.session.post(
                    self.url, json=self.payload(messages, max_tokens, probe),
                    timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                r["status"] = resp.status
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    r["error"] = f"http_{resp.status}"
                    r["error_detail"] = body
                    r["e2e"] = time.perf_counter() - t0
                    return r
                buf = b""
                async for raw in resp.content.iter_any():
                    buf += raw
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line.startswith(b"data:"):
                            continue
                        data = line[5:].strip()
                        if data == b"[DONE]":
                            continue
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("usage"):
                            usage = obj["usage"]
                        for ch in obj.get("choices") or []:
                            d = ch.get("delta") or {}
                            reas = d.get("reasoning_content") or d.get("reasoning") or ""
                            content = d.get("content") or ""
                            if reas:
                                r["reasoning"] = True
                            if probe and content:
                                parts.append(content)
                            if ch.get("finish_reason"):
                                r["finish"] = ch["finish_reason"]
                            if content or reas:
                                now = time.perf_counter()
                                if r["tp_first"] is None:
                                    r["tp_first"] = now
                                    r["ttft"] = now - t0
                                else:
                                    r["max_gap"] = max(r["max_gap"] or 0.0, now - r["tp_last"])
                                if content and r["ttfc"] is None:
                                    r["ttfc"] = now - t0
                                r["tp_last"] = now
                                n_chunks += 1
            r["e2e"] = time.perf_counter() - t0
            if probe:
                r["text"] = "".join(parts)
            if usage and usage.get("completion_tokens"):
                r["out_tokens"] = usage["completion_tokens"]
                r["in_tokens"] = usage.get("prompt_tokens")
                r["usage"] = True
            else:
                r["out_tokens"] = n_chunks
            if n_chunks > 1:
                r["itl"] = (r["tp_last"] - r["tp_first"]) / (n_chunks - 1)
            if r["ttft"] is None:
                r["error"] = "leere_antwort"
            else:
                r["ok"] = True
        except TimeoutError:
            r["error"] = "timeout"
            r["e2e"] = time.perf_counter() - t0
        except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError,
                ConnectionResetError, aiohttp.ClientOSError) as e:
            r["error"] = "verbindung"
            r["error_detail"] = str(e)[:200]
            r["e2e"] = time.perf_counter() - t0
        except Exception as e:  # noqa
            r["error"] = type(e).__name__
            r["error_detail"] = str(e)[:200]
            r["e2e"] = time.perf_counter() - t0
        return r

    async def ping(self):
        """Dauer einer sehr kleinen Anfrage (/models) in ms – misst die Netzwerkverzögerung."""
        t0 = time.perf_counter()
        try:
            async with self.session.get(self.args.base_url.rstrip("/") + "/models",
                                        timeout=aiohttp.ClientTimeout(total=5)) as resp:
                await resp.read()
                return (time.perf_counter() - t0) * 1000 if resp.status < 500 else None
        except Exception:
            return None

    async def alive(self):
        return (await self.ping()) is not None

    async def model_info(self):
        try:
            async with self.session.get(self.args.base_url.rstrip("/") + "/models",
                                        timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return await resp.json(content_type=None)
        except Exception:
            return None


# ── Messfenster-Rechnungen ─────────────────────────────────────────────────

def tokens_in_window(r, a, b):
    """Anteil der Ausgabe-Tokens einer Anfrage, die im Zeitfenster [a, b) entstanden sind
    (gleichmäßige Verteilung zwischen erstem und letztem Textstück)."""
    if not r.get("ok") or not r.get("out_tokens"):
        return 0.0
    s, e = r["tp_first"], r["tp_last"]
    if e is None or s is None:
        return 0.0
    if e - s <= 1e-6:
        return float(r["out_tokens"]) if a <= s < b else 0.0
    overlap = max(0.0, min(e, b) - max(s, a))
    return r["out_tokens"] * overlap / (e - s)


def window_tps(results, a, b):
    if b <= a:
        return None
    return sum(tokens_in_window(r, a, b) for r in results) / (b - a)


async def run_batch(client, job_fn, n_requests, concurrency):
    """n_requests Anfragen mit höchstens `concurrency` gleichzeitig.
    job_fn() liefert (Nachrichten, Ausgabelänge)."""
    sem = asyncio.Semaphore(concurrency)
    results = []

    async def one(i):
        async with sem:
            msgs, n_out = job_fn()
            res = await client.request(msgs, n_out)
            res["concurrency"] = concurrency
            results.append(res)

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(n_requests)))
    return results, time.perf_counter() - t0


MAX_INFLIGHT = 1000  # Schutz für den Messrechner bei offener Last


async def run_rate(client, job_fn, rate, duration, warmup, drain, rnd):
    """Offene Last: Anfragen kommen zufällig (Poisson) mit `rate` pro Sekunde – egal, wie
    schnell der Server antwortet. So entsteht bei Überlast eine echte Warteschlange, die bei
    fester Parallelität verborgen bliebe. Gemessen werden Anfragen, die nach der Anlaufzeit
    ankommen. Nach dem Ende wird höchstens `drain` s auf offene Antworten gewartet; wer dann
    noch wartet, zählt als Zeitüberschreitung."""
    warmup = min(warmup, duration / 3)
    t0 = time.perf_counter()
    end, deadline = t0 + duration, t0 + duration + drain
    results, tasks, late = [], set(), []
    st = {"inflight": 0, "max_inflight": 0}

    async def one(msgs, n_out):
        st["inflight"] += 1
        st["max_inflight"] = max(st["max_inflight"], st["inflight"])
        try:
            timeout = min(client.args.timeout, max(1.0, deadline - time.perf_counter()))
            r = await client.request(msgs, n_out, timeout=timeout)
        finally:
            st["inflight"] -= 1
        r["rate"] = rate
        results.append(r)

    t_next = t0
    while True:
        t_next += rnd.expovariate(rate)
        if t_next >= end:
            break
        delay = t_next - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        late.append(max(0.0, time.perf_counter() - t_next))
        if st["inflight"] >= MAX_INFLIGHT:
            r = client.blank_result()
            r.update(error="zu_viele_offen", e2e=0.0, rate=rate)
            results.append(r)
            continue
        msgs, n_out = job_fn()
        tk = asyncio.create_task(one(msgs, n_out))
        tasks.add(tk)
        tk.add_done_callback(tasks.discard)
    if tasks:
        await asyncio.gather(*list(tasks))
    return results, t0 + warmup, end, st["max_inflight"], pct(late, 95)


async def run_timed(client, job_fn, c, duration, warmup, min_samples, max_duration):
    """Hält `c` Anfragen dauerhaft gleichzeitig am Laufen.
    Gemessen wird nur im eingeschwungenen Zustand: nach der Anlaufzeit (warmup) bis zu dem
    Moment, in dem die erste Arbeitskraft aufhört – vorher sind immer alle c Plätze belegt.
    Die Messung verlängert sich, bis mindestens `min_samples` Anfragen im Fenster
    gestartet wurden (höchstens bis max_duration)."""
    warmup = min(warmup, duration / 3)
    results = []
    t0 = time.perf_counter()
    st = {"win_start": t0 + warmup, "started": 0, "launch_end": None, "ok_e2e": []}

    def backoff():
        # Wer eine Fehlermeldung bekommt, versucht es nach einer Weile erneut – ungefähr
        # so lange, wie eine normale Antwort dauert (mind. 1 s). Sonst würde ein überlasteter
        # Server mit tausenden sofortigen Wiederholungen geflutet und die Fehlerquote verzerrt.
        recent = st["ok_e2e"][-50:]
        return min(10.0, max(1.0, pct(recent, 50) or 1.0))

    async def worker():
        while True:
            now = time.perf_counter()
            if now >= t0 + duration and (st["started"] >= min_samples or now >= t0 + max_duration):
                if st["launch_end"] is None:
                    st["launch_end"] = now
                return
            if now >= st["win_start"]:
                st["started"] += 1
            msgs, n_out = job_fn()
            r = await client.request(msgs, n_out)
            r["concurrency"] = c
            results.append(r)
            if r["ok"]:
                st["ok_e2e"].append(r["e2e"])
            else:
                await asyncio.sleep(backoff())

    await asyncio.gather(*(worker() for _ in range(c)))
    win_end = st["launch_end"] or time.perf_counter()
    return results, st["win_start"], win_end


def summarize(results, wall):
    ok = [r for r in results if r["ok"]]
    n = len(results)
    tpots = []
    per_user = []
    for r in ok:
        if r["out_tokens"] > 1 and r["e2e"] and r["ttft"] is not None:
            dec = r["e2e"] - r["ttft"]
            if dec > 0:
                tpots.append(dec / (r["out_tokens"] - 1))
                per_user.append((r["out_tokens"] - 1) / dec)
    ttfts = [r["ttft"] for r in ok]
    e2es = [r["e2e"] for r in ok]
    gaps = [r["max_gap"] for r in ok if r.get("max_gap") is not None]
    ttfcs = [r["ttfc"] for r in ok if r.get("reasoning") and r.get("ttfc") is not None]
    out_sum = sum(r["out_tokens"] for r in ok)
    in_sum = sum(r["in_tokens"] or 0 for r in ok)
    errs = Counter(r["error"] for r in results if not r["ok"])
    return {
        "n": n, "ok": len(ok), "errors": n - len(ok),
        "error_rate": (n - len(ok)) / n if n else 0.0,
        "error_types": dict(errs),
        "wall_s": wall,
        # p99 erst ab 100 Werten – darunter ist es praktisch nur der Maximalwert
        "ttft_p50": pct(ttfts, 50), "ttft_p95": pct(ttfts, 95),
        "ttft_p99": pct(ttfts, 99) if len(ttfts) >= 100 else None,
        "ttft_max": max(ttfts) if ttfts else None,
        "ttfc_p50": pct(ttfcs, 50), "ttfc_p95": pct(ttfcs, 95),
        "stall_p50": pct(gaps, 50), "stall_p95": pct(gaps, 95),
        "stall_max": max(gaps) if gaps else None,
        "tpot_p50": pct(tpots, 50), "tpot_p95": pct(tpots, 95),
        "user_tps_p50": pct(per_user, 50),
        "user_tps_min": min(per_user) if per_user else None,
        "user_tps_max": max(per_user) if per_user else None,
        "e2e_p50": pct(e2es, 50), "e2e_p95": pct(e2es, 95), "e2e_mean": mean(e2es),
        "out_tps": out_sum / wall if wall else None,
        "total_tps": (out_sum + in_sum) / wall if wall else None,
        "req_s": len(ok) / wall if wall else None,
        "in_tokens_avg": mean([r["in_tokens"] for r in ok]),
        "out_tokens_avg": mean([r["out_tokens"] for r in ok]),
    }


def goodput(results, slo_ttft, slo_tps):
    """Anteil (%) der Anfragen, die beide Ziele einzeln einhalten. Fehler zählen als verfehlt."""
    if not results:
        return None
    good = 0
    for r in results:
        if not r["ok"] or r["ttft"] is None or r["ttft"] > slo_ttft:
            continue
        if r["out_tokens"] > 1 and r["e2e"]:
            dec = r["e2e"] - r["ttft"]
            if dec <= 0 or (r["out_tokens"] - 1) / dec < slo_tps:
                continue
        good += 1
    return good / len(results) * 100


def summarize_timed(results, win_start, win_end, c, slo=None):
    """Kennzahlen aus dem eingeschwungenen Messfenster. slo = (TTFT-Ziel, Tempo-Ziel)."""
    L = max(1e-6, win_end - win_start)
    inwin = [r for r in results if win_start <= r["tp_start"] < win_end]
    s = summarize(inwin, L)
    if slo:
        s["goodput_pct"] = goodput(inwin, *slo)
    s["out_tps"] = window_tps(results, win_start, win_end)
    done = [r for r in results if r["ok"] and win_start <= r["tp_start"] + r["e2e"] < win_end]
    s["req_s"] = len(done) / L
    s["total_tps"] = (s["out_tps"] or 0) + sum(r["in_tokens"] or 0 for r in done) / L
    thirds = [window_tps(results, win_start + i * L / 3, win_start + (i + 1) * L / 3)
              for i in range(3)]
    thirds = [t for t in thirds if t is not None]
    m = mean(thirds)
    s["stability_pct"] = (max(thirds) - min(thirds)) / m * 100 if m else None
    s["window_s"] = L
    s["n_window"] = len(inwin)
    s["concurrency"] = c
    return s


def meets_slo(s, slo_ttft, slo_tps):
    return (s["error_rate"] == 0 and s["ttft_p95"] is not None and s["ttft_p95"] <= slo_ttft
            and s["user_tps_p50"] is not None and s["user_tps_p50"] >= slo_tps)


def recommended_concurrency(summary, a=None):
    """Höchste Parallelität, bei der die Zielwerte eingehalten werden."""
    cfg = summary.get("config", {})
    slo_t = cfg.get("slo_ttft", getattr(a, "slo_ttft", 2.0))
    slo_u = cfg.get("slo_user_tps", getattr(a, "slo_user_tps", 10.0))
    best = None
    for s in sorted((summary.get("ramp") or {}).get("steps", []), key=lambda x: x["concurrency"]):
        if meets_slo(s, slo_t, slo_u):
            best = s["concurrency"]
    return best


def users_for(req_s, e2e, think):
    """Gesetz von Little: Ein aktiver Nutzer stellt alle (Antwortdauer + Denkpause) Sekunden
    eine Frage. req_s Fragen pro Sekunde reichen also für req_s × (e2e + think) Nutzer."""
    if not req_s or e2e is None:
        return None
    return req_s * (e2e + think)


def round_users(v):
    """Nutzerzahlen grob runden – mehr Genauigkeit gibt die Schätzung nicht her."""
    if v is None or v < 1:
        return v
    step = 100 if v >= 1000 else 10 if v >= 100 else 5 if v >= 30 else 1
    return max(step, round(v / step) * step)


def rate_ok(s, slo_t, slo_u):
    return meets_slo(s, slo_t, slo_u) and not s.get("overloaded")


def capacity(summary):
    """Für wie viele aktive Nutzer reicht der Server? Bevorzugt aus der offenen Last
    (realistischer, weil Warteschlangen sichtbar werden), sonst aus der Ramp."""
    cfg = summary.get("config") or {}
    think = cfg.get("think_time", 60.0)
    slo_t, slo_u = cfg.get("slo_ttft", 2.0), cfg.get("slo_user_tps", 10.0)
    out = {"think_time": think}
    rec = recommended_concurrency(summary)
    step = next((s for s in (summary.get("ramp") or {}).get("steps", [])
                 if s["concurrency"] == rec), None)
    if step:
        out["rec_concurrency"] = rec
        out["users_ramp"] = users_for(step.get("req_s"), step.get("e2e_mean") or step.get("e2e_p50"),
                                      think)
    good = [s for s in (summary.get("rate") or {}).get("stages", []) if rate_ok(s, slo_t, slo_u)]
    if good:
        g = max(good, key=lambda s: s["rate"])
        out["rate_ok"] = g["rate"]
        out["users_rate"] = users_for(g.get("rate_actual") or g["rate"],
                                      g.get("e2e_mean") or g.get("e2e_p50"), think)
    out["users"] = out.get("users_rate") or out.get("users_ramp")
    out["source"] = ("rate" if out.get("users_rate") else "ramp" if out.get("users_ramp")
                     else None)
    return out


# ════════════════════════════════════════════════════════════════════════════
#  Antwortqualität: Kontrollfragen mit eindeutig prüfbarer Antwort
# ════════════════════════════════════════════════════════════════════════════

CAPITALS = [("Frankreich", ["paris"]), ("Italien", ["rom", "rome"]), ("Spanien", ["madrid"]),
            ("Japan", ["tokio", "tokyo"]), ("Kanada", ["ottawa"]), ("Australien", ["canberra"]),
            ("Österreich", ["wien", "vienna"]), ("Polen", ["warschau", "warsaw"]),
            ("Norwegen", ["oslo"]), ("Ägypten", ["kairo", "cairo"]),
            ("Portugal", ["lissabon", "lisbon"]), ("Schweden", ["stockholm"])]
NAMES = ["Anna", "Ben", "Clara", "David", "Elif", "Finn", "Greta", "Hannes", "Ida", "Jonas"]
PROBE_KINDS = {"rechnen": "Rechnen", "sortieren": "Sortieren", "wissen": "Wissen",
               "json": "Format (JSON)"}


class Probes:
    """Erzeugt Kontrollfragen (Rechnen, Sortieren, Wissen, JSON-Format) und prüft die Antworten.
    Die Zahlen sind jedes Mal neu, damit kein Cache die richtige Antwort liefert."""

    def __init__(self, seed):
        self.rnd = random.Random(seed + 2)
        self.i = 0

    def make(self):
        kinds = list(PROBE_KINDS)
        kind = kinds[self.i % len(kinds)]
        self.i += 1
        r = self.rnd
        if kind == "rechnen":
            a, b = r.randint(100, 999), r.randint(100, 999)
            return kind, f"Was ist {a} + {b}? Antworte nur mit der Zahl.", a + b
        if kind == "sortieren":
            nums = r.sample(range(1, 100), 5)
            return (kind, f"Sortiere diese Zahlen aufsteigend: {', '.join(map(str, nums))}. "
                          "Antworte nur mit den Zahlen, durch Komma getrennt.", sorted(nums))
        if kind == "wissen":
            land, ok = r.choice(CAPITALS)
            return kind, f"Wie heißt die Hauptstadt von {land}? Antworte nur mit dem Namen der Stadt.", ok
        name, age = r.choice(NAMES), r.randint(18, 80)
        return (kind, 'Gib ein JSON-Objekt mit den Schlüsseln "name" und "alter" zurück. '
                      f"name ist {name}, alter ist {age}. Antworte nur mit dem JSON.",
                {"name": name, "alter": age})

    @staticmethod
    def check(kind, text, expected):
        t = re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S).strip()
        if not t:
            return False
        if kind == "rechnen":
            t = re.sub(r"(?<=\d)[.\s'’](?=\d{3}\b)", "", t)  # Tausenderpunkte
            nums = re.findall(r"\d+", t)
            return bool(nums) and int(nums[-1]) == expected
        if kind == "sortieren":
            nums = [int(x) for x in re.findall(r"\d+", t)]
            return nums[-len(expected):] == expected
        if kind == "wissen":
            return any(o in t.lower() for o in expected)
        m = re.search(r"\{.*\}", t, re.S)
        try:
            obj = json.loads(m.group(0)) if m else None
            return (isinstance(obj, dict) and str(obj.get("name", "")).strip() == expected["name"]
                    and int(obj.get("alter")) == expected["alter"])
        except (ValueError, TypeError):
            return False


def probe_summary(log_):
    """Kontrollfragen je Phase zusammenfassen. status: richtig | falsch | abgeschnitten | fehler."""
    if not log_:
        return None
    groups = {}
    for p in log_:
        g = groups.setdefault((p["phase"], p["label"]), {
            "phase": p["phase"], "label": p["label"], "key": p.get("key"),
            "n": 0, "richtig": 0, "falsch": 0, "abgeschnitten": 0, "fehler": 0})
        g["n"] += 1
        g[p["status"]] += 1
    order = {"alone": 0, "ramp": 1, "rate": 2, "soak": 3}
    out = sorted(groups.values(), key=lambda g: (order.get(g["phase"], 9), g["key"] or 0))
    for g in out:
        g["pct"] = g["richtig"] / g["n"] * 100

    def share(items):
        n = sum(g["n"] for g in items)
        return sum(g["richtig"] for g in items) / n * 100 if n else None

    alone = [g for g in out if g["phase"] == "alone"]
    load = [g for g in out if g["phase"] != "alone"]
    kinds = {}
    for p in log_:
        k = kinds.setdefault(p["kind"], [0, 0])
        k[0] += p["status"] == "richtig"
        k[1] += 1
    return {"groups": out, "alone_pct": share(alone), "load_pct": share(load),
            "n_alone": sum(g["n"] for g in alone), "n_load": sum(g["n"] for g in load),
            "worst": min(load, key=lambda g: g["pct"]) if load else None,
            "by_kind": {k: v[0] / v[1] * 100 for k, v in kinds.items()},
            "wrong": [p for p in log_ if p["status"] != "richtig"][:8]}


# ════════════════════════════════════════════════════════════════════════════
#  Wirtschaftlichkeit und Gesamturteil
# ════════════════════════════════════════════════════════════════════════════

ECON_DEFAULTS = {"hw_price": 4000.0, "amort_months": 36, "server_watts": 200.0,
                 "power_price": 0.30, "cloud_price_in": 0.50, "cloud_price_out": 1.50,
                 "work_hours": 168.0}


def economics(summary):
    """Was kostet der eigene Server im Monat, und was kostete dieselbe Menge in der Cloud?
    Grundlage ist der Lastpunkt, bei dem die Ziele noch eingehalten werden."""
    cfg = summary.get("config") or {}
    c = {k: cfg.get(k) if cfg.get(k) is not None else v for k, v in ECON_DEFAULTS.items()}
    cfg_slo = (cfg.get("slo_ttft", 2.0), cfg.get("slo_user_tps", 10.0))
    point = None
    good = [s for s in (summary.get("rate") or {}).get("stages", []) if rate_ok(s, *cfg_slo)]
    if good:
        g = max(good, key=lambda s: s["rate"])
        point = (g.get("rate_actual") or g["rate"], g.get("in_tokens_avg"), g.get("out_tokens_avg"))
    else:
        rec = recommended_concurrency(summary)
        st = next((s for s in (summary.get("ramp") or {}).get("steps", [])
                   if s["concurrency"] == rec), None)
        if st:
            point = (st.get("req_s"), st.get("in_tokens_avg"), st.get("out_tokens_avg"))
    if not point or not point[0]:
        return None
    req_s, in_avg, out_avg = point
    in_avg = in_avg or cfg.get("input_len", 1024)
    out_avg = out_avg or cfg.get("output_len", 256)
    hw_month = c["hw_price"] / max(1, c["amort_months"])
    power_month = c["server_watts"] / 1000 * 730 * c["power_price"]  # läuft rund um die Uhr
    own = hw_month + power_month
    answers = req_s * 3600 * c["work_hours"]  # Antworten/Monat bei voller Nutzung
    cloud_full = answers * (in_avg * c["cloud_price_in"] + out_avg * c["cloud_price_out"]) / 1e6
    users = capacity(summary).get("users")
    return {**c, "own_month": own, "hw_month": hw_month, "power_month": power_month,
            "answers_month": answers, "cloud_full_month": cloud_full,
            "own_per_1000": own / answers * 1000 if answers else None,
            "cloud_per_1000": cloud_full / answers * 1000 if answers else None,
            "breakeven_pct": own / cloud_full * 100 if cloud_full else None,
            "own_per_user": own / users if users else None,
            "in_avg": in_avg, "out_avg": out_avg, "req_s": req_s}


def verdict(summary):
    """Empfehlung in einem Satz: good | warn | bad plus Begründungen."""
    cfg = summary.get("config") or {}
    cap_ = capacity(summary)
    users, target = cap_.get("users"), cfg.get("target_users") or 0
    rank = {"good": 0, "warn": 1, "bad": 2}
    st, reasons = "good", []

    def note(status, text):
        nonlocal st
        if rank[status] > rank[st]:
            st = status
        reasons.append((status, text))

    tested = (summary.get("ramp") or {}).get("steps") or (summary.get("rate") or {}).get("stages")
    if tested:
        if not users:
            note("bad", "Schon bei geringer Last werden die Ziele für Wartezeit und Tempo verfehlt.")
        elif target:
            if users >= target:
                note("good", f"Reicht für ≈ {fmt(round_users(users), 0)} aktive Nutzer – gebraucht werden {target}.")
            elif users >= 0.7 * target:
                note("warn", f"Knapp: reicht für ≈ {fmt(round_users(users), 0)} aktive Nutzer, gebraucht werden {target}.")
            else:
                note("bad", f"Reicht nur für ≈ {fmt(round_users(users), 0)} aktive Nutzer, gebraucht werden {target}.")
        else:
            note("good", f"Reicht für ≈ {fmt(round_users(users), 0)} aktive Nutzer gleichzeitig.")
    pr = summary.get("probes")
    if pr and pr.get("load_pct") is not None:
        ref = pr.get("alone_pct") if pr.get("alone_pct") is not None else 100.0
        drop = ref - pr["load_pct"]
        if drop > 10:
            note("bad", f"Unter Last werden die Antworten schlechter: {fmt(pr['load_pct'], 0)} % richtig "
                        f"statt {fmt(ref, 0)} % ohne Last.")
        elif drop > 3:
            note("warn", f"Unter Last etwas weniger richtige Antworten ({fmt(pr['load_pct'], 0)} % "
                         f"statt {fmt(ref, 0)} %).")
        else:
            note("good", f"Die Antworten bleiben unter Last genauso gut ({fmt(pr['load_pct'], 0)} % richtig).")
    if summary.get("crashes"):
        note("bad", "Der Server ist während des Tests abgestürzt.")
    eco = economics(summary)
    if eco and eco.get("breakeven_pct") is not None:
        if eco["breakeven_pct"] > 100:
            note("warn", "Selbst bei voller Auslastung wäre die Cloud günstiger (bei den eingetragenen Preisen).")
        else:
            note("good", f"Günstiger als die Cloud, sobald er zu {fmt(eco['breakeven_pct'], 0)} % "
                         "der Arbeitszeit ausgelastet ist.")
    q = (summary.get("quality") or {}).get("overall")
    if q == "niedrig":
        note("warn", "Die Messung selbst war nicht ganz sauber – Test wiederholen, bevor entschieden wird.")
    headline = {"good": "Der Server ist für unseren Einsatz geeignet.",
                "warn": "Der Server ist geeignet – mit Einschränkungen.",
                "bad": "Der Server reicht in dieser Form nicht aus."}[st]
    if not tested and not pr:
        headline, st = "Für ein Urteil fehlen die Lasttests.", "warn"
    return {"status": st, "headline": headline, "reasons": reasons}


# ════════════════════════════════════════════════════════════════════════════
#  Die einzelnen Tests
# ════════════════════════════════════════════════════════════════════════════

class StressTest:
    def __init__(self, args, outdir):
        self.a = args
        self.outdir = outdir
        self.raw = open(os.path.join(outdir, "raw_requests.jsonl"), "w", encoding="utf-8")
        if args.seed is None:  # immer einen Seed festhalten, damit der Lauf wiederholbar ist
            args.seed = random.randrange(1, 2 ** 31)
        self.prefix_note = None
        if args.shared_prefix and args.shared_prefix > args.input_len - 64:
            fixed = max(0, int(args.input_len * 0.75))
            self.prefix_note = (f"Gemeinsamer Anfang ({args.shared_prefix} Tokens) ist länger als "
                                f"die Frage – auf {fixed} Tokens gekürzt.")
            args.shared_prefix = fixed
        self.summary = {"meta": {}, "config": {k: v for k, v in vars(args).items()
                                                if k != "api_key"}}
        self.pf = PromptFactory(seed=args.seed, shared_prefix=args.shared_prefix)
        self.arrivals = random.Random(args.seed + 1)  # Zufallsankünfte der offenen Last
        self.probes = Probes(args.seed)
        self.probe_log = []
        self.probe_tokens = 64
        metrics_url = args.metrics_url
        if metrics_url is None:
            root = re.sub(r"/v1/?$", "", args.base_url.rstrip("/"))
            metrics_url = root + "/metrics"
        lm = args.local_monitor
        local = is_local_url(args.base_url) if lm == "auto" else lm == "on"
        self.mon = Monitor(args.monitor_interval, metrics_url if metrics_url != "off" else None,
                           local=local)
        self.summary["meta"]["local_monitor"] = local
        self.server_down = False
        self.on_update = None  # Callback, wenn neue Teilergebnisse vorliegen
        self.lags = []         # (Zeitpunkt, Verzögerung in s) der eigenen Ereignisschleife

    def save_raw(self, test, results, **extra):
        for r in results:
            rec = {"test": test, **extra, **r}
            self.raw.write(json.dumps(rec) + "\n")
        self.raw.flush()

    def save_summary(self):
        self.summary["monitor"] = self.mon.samples
        self.summary["meta"]["gpu_name"] = self.mon.gpu_name
        self.summary["meta"]["has_server_metrics"] = bool(self.mon.has_metrics)
        self.derive()  # vor dem Schreiben, damit die Datei das aktuelle Urteil enthält
        with open(os.path.join(self.outdir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(self.summary, f, indent=1, default=str)
        self.notify()

    def derive(self):
        """Abgeleitete Kennzahlen: Nutzerzahl, Kontrollfragen, Kosten, Gesamturteil."""
        self.summary["capacity"] = capacity(self.summary)
        self.summary["probes"] = probe_summary(self.probe_log)
        self.summary["economics"] = economics(self.summary)
        self.summary["verdict"] = verdict(self.summary)

    def notify(self):
        self.derive()
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                pass

    # ── Aufpasser: kommt der Messrechner selbst hinterher? ─────────────────
    async def lag_watch(self):
        """Misst, wie verspätet ein 100-ms-Wecker klingelt. Ist der Messrechner mit dem
        Verarbeiten der Antworten überlastet, kommt der Wecker zu spät – dann wären auch
        die gemessenen Wartezeiten zu hoch."""
        while True:
            t = time.perf_counter()
            await asyncio.sleep(0.1)
            self.lags.append((t, max(0.0, time.perf_counter() - t - 0.1)))
            if len(self.lags) > 200000:
                del self.lags[:50000]

    def lag_ms(self, a, b):
        vals = [lag for t, lag in self.lags if a <= t < b]
        v = pct(vals, 95)
        return v * 1000 if v is not None else None

    # ── Anfragen für die Lasttests ──────────────────────────────────────────
    def job(self):
        """(Nachrichten, Ausgabelänge) für Ramp, offene Last, Ansturm und Ausdauer.
        Bei length_mix = mixed schwanken die Längen wie im Alltag (log-normal um den
        eingestellten Wert: viele kurze Fragen, einige sehr lange)."""
        a = self.a
        n_in, n_out = a.input_len, a.output_len
        if a.length_mix == "mixed":
            r = self.pf.rnd
            n_in = int(min(a.input_len * 8, max(64, r.lognormvariate(math.log(a.input_len), 0.8))))
            n_out = int(min(a.output_len * 4, max(16, r.lognormvariate(math.log(a.output_len), 0.6))))
            lim = a.max_context or self.summary["meta"].get("max_model_len")
            if lim:
                n_in = max(64, min(n_in, int(lim * 0.9) - n_out))
        return self.pf.make(n_in, shared=True), n_out

    def fixed_job(self):
        """Immer gleich lange Anfrage – für Baseline, Kontrolle und Erholungsprüfung."""
        return self.pf.make(self.a.input_len, shared=True), self.a.output_len

    # ── Zähler des Servers (Verdrängungen, Prefix-Cache) ────────────────────
    async def counters(self):
        if not self.mon.metrics_url:
            return {}
        return await asyncio.get_running_loop().run_in_executor(None, self.mon._server) or {}

    @staticmethod
    def counter_delta(c0, c1, s):
        """Schreibt Verdrängungen und Prefix-Cache-Trefferquote zwischen zwei Abfragen in s."""
        if "preempt_total" in c0 and "preempt_total" in c1:
            s["preemptions"] = max(0, int(round(c1["preempt_total"] - c0["preempt_total"])))
        dq = c1.get("pc_queries", 0) - c0.get("pc_queries", 0)
        if "pc_queries" in c1 and dq > 0:
            s["prefix_hit_pct"] = (c1.get("pc_hits", 0) - c0.get("pc_hits", 0)) / dq * 100
        elif c1.get("pc_rate") is not None:
            s["prefix_hit_pct"] = c1["pc_rate"]

    # ── Kontrollfragen ──────────────────────────────────────────────────────
    async def _probe_once(self, client, phase, label, key=None):
        kind, q, expected = self.probes.make()
        r = await client.request([{"role": "user", "content": q}], self.probe_tokens, probe=True)
        if not r["ok"]:
            status = "fehler"
        elif Probes.check(kind, r.get("text"), expected):
            status = "richtig"
        elif r.get("finish") == "length":
            status = "abgeschnitten"
        else:
            status = "falsch"
        rec = {"phase": phase, "label": label, "key": key, "kind": kind, "status": status,
               "frage": q, "antwort": (r.get("text") or r.get("error") or "")[:200],
               "erwartet": expected, "ttft": r["ttft"], "e2e": r["e2e"]}
        self.probe_log.append(rec)
        self.raw.write(json.dumps({"test": "probe", **rec}, default=str) + "\n")
        return rec

    async def _probe_loop(self, client, phase, label, key):
        await asyncio.sleep(min(self.a.warmup_seconds, 5))
        while True:
            await self._probe_once(client, phase, label, key)
            await asyncio.sleep(self.a.probe_interval)

    @contextlib.asynccontextmanager
    async def probing(self, client, phase, label, key=None):
        """Stellt während einer Laststufe nebenher Kontrollfragen (höchstens eine gleichzeitig)."""
        task = None
        if self.a.probe_interval > 0:
            task = asyncio.create_task(self._probe_loop(client, phase, label, key))
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def probe_alone(self, client):
        n = self.a.probe_count
        if n <= 0 or self.a.probe_interval <= 0:
            return
        log(f"  Kontrollfragen ohne Last: {n} Stück …")
        self.mon.phase = "probes"
        res = [await self._probe_once(client, "alone", "allein") for _ in range(n)]
        ok = sum(r["status"] == "richtig" for r in res)
        log(f"      → {ok} von {n} richtig")

    async def check_crash(self, client, label):
        """Nach Verbindungsfehlern prüfen, ob der Server noch lebt; ggf. warten."""
        if await client.alive():
            return False
        log(f"  ⚠ Server antwortet nicht mehr ({label}). Warte bis zu "
            f"{self.a.recovery_wait:.0f}s auf Neustart …")
        crash = {"when": label, "t": time.time() - self.mon.t0, "recovered_after_s": None}
        t0 = time.time()
        while time.time() - t0 < self.a.recovery_wait:
            await asyncio.sleep(5)
            if await client.alive():
                crash["recovered_after_s"] = time.time() - t0
                log(f"  ✓ Server wieder erreichbar nach {crash['recovered_after_s']:.0f}s")
                break
        self.summary.setdefault("crashes", []).append(crash)
        if crash["recovered_after_s"] is None:
            log("  ✗ Server bleibt unerreichbar – restliche Tests werden übersprungen.")
            self.server_down = True
        return True

    # ── 0. Vorbereitung und Vorab-Checks ────────────────────────────────────
    async def preflight(self, client):
        log("Vorbereitung: Server erreichbar?")
        info = await client.model_info()
        if info is None:
            hint = ""
            if IN_DOCKER and (urlparse(self.a.base_url).hostname or "") in ("localhost", "127.0.0.1", "::1"):
                hint = (" Hinweis: Im Docker-Container ist „localhost“ der Container selbst – für einen "
                        "Modellserver auf diesem Rechner host.docker.internal statt localhost eintragen.")
            raise PreflightError(f"Server unter {self.a.base_url} nicht erreichbar.{hint}")
        models = [m.get("id") for m in info.get("data", [])] if isinstance(info, dict) else []
        if not self.a.model:
            if not models:
                raise PreflightError("Kein Modell gefunden – bitte Modellnamen angeben.")
            self.a.model = models[0]
            self.summary["config"]["model"] = self.a.model
        max_len = None
        for m in info.get("data", []) if isinstance(info, dict) else []:
            if m.get("id") == self.a.model:
                max_len = m.get("max_model_len") or m.get("context_length")
        self.summary["meta"].update({"models": models, "server_max_model_len": max_len,
                                     "started": dt.datetime.now().isoformat(timespec="seconds"),
                                     "host": platform.node(), "version": VERSION,
                                     "server_host": urlparse(self.a.base_url).hostname})
        log(f"  Modell: {self.a.model}   max. Kontext: {max_len or 'unbekannt'}")
        pre = {}

        # Netzwerkverzögerung
        pings = [p for p in [await client.ping() for _ in range(10)] if p is not None]
        pre["rtt_ms"] = pct(pings, 50)
        log(f"  Netzwerkverzögerung: {fmt(pre['rtt_ms'], 1)} ms")

        # Ist der Server gerade frei? (nur mit /metrics möglich)
        loop = asyncio.get_running_loop()
        m = await loop.run_in_executor(None, self.mon._server)
        if m and ("running" in m or "waiting" in m):
            pre["busy"] = int((m.get("running") or 0) + (m.get("waiting") or 0))
            log(f"  Laufende Anfragen vor dem Test: {pre['busy']}")
        else:
            pre["busy"] = None

        # Test-Anfrage + prüfen, ob ignore_eos akzeptiert wird
        r = await client.request(self.pf.make(64), 16)
        if not r["ok"] and client.use_ignore_eos and r.get("status") == 400:
            log("  Server akzeptiert 'ignore_eos' nicht – Antwortlänge ist dadurch variabel.")
            client.use_ignore_eos = False
            r = await client.request(self.pf.make(64), 16)
        if not r["ok"]:
            raise PreflightError(f"Test-Anfrage fehlgeschlagen: {r.get('error')} "
                                 f"{r.get('error_detail', '')}")
        self.summary["meta"]["ignore_eos"] = client.use_ignore_eos
        pre["usage"] = r["usage"]
        pre["thinking"] = r["reasoning"]

        # Kalibrierung Füllwörter → Tokens
        test_words = 800
        r2 = await client.request(self.pf.make(int(test_words * self.pf.tpw) + 40), 4)
        if r2["ok"] and r2["in_tokens"]:
            self.pf.tpw = max(0.5, (r2["in_tokens"] - 40) / test_words)
            log(f"  Kalibriert: {self.pf.tpw:.2f} Tokens pro Füllwort")
        else:
            log("  Server liefert keine Token-Zählung – Längen werden geschätzt.")
        self.summary["meta"]["tokens_per_word"] = self.pf.tpw
        self.summary["meta"]["max_model_len"] = max_len

        # Aufwärmen (legt auch den gemeinsamen Anfang in den Cache) + prüfen, ob die
        # Antwortlänge wirklich fest ist
        if self.prefix_note:
            log("  " + self.prefix_note)
        warm = [await client.request(self.pf.make(self.a.input_len, shared=True), 32)
                for _ in range(3)]
        outs = [w["out_tokens"] for w in warm if w["ok"]]
        pre["fixed_length"] = bool(outs) and client.use_ignore_eos and min(outs) >= 32 * 0.9
        pre["thinking"] = pre["thinking"] or any(w["reasoning"] for w in warm)
        if pre["thinking"]:
            log("  Hinweis: Modell 'denkt' vor der Antwort (Thinking-Modus).")
        log(f"  Seed {self.a.seed} · Längen {'gemischt' if self.a.length_mix == 'mixed' else 'fest'}"
            + (f" · gemeinsamer Anfang {self.a.shared_prefix} Tokens" if self.a.shared_prefix else ""))
        self.summary["prechecks"] = pre
        if pre["thinking"] and not self.a.disable_thinking:
            self.probe_tokens = self.a.probe_thinking_tokens
        self.notify()

    # ── 1. Baseline ─────────────────────────────────────────────────────────
    async def _single_run(self, client, label, shared=True):
        a = self.a
        res, wall = await run_batch(
            client, lambda: (self.pf.make(a.input_len, shared=shared), a.output_len),
            a.baseline_requests, 1)
        s = summarize(res, wall)
        self.save_raw(label, res)
        return s

    async def baseline(self, client):
        log("━━ 1/6 Einer allein (Baseline) ━━")
        self.mon.phase = "baseline"
        c0 = await self.counters()
        s = await self._single_run(client, "baseline")
        self.counter_delta(c0, await self.counters(), s)
        if self.a.shared_prefix:
            # Vergleich: dieselben Fragen ohne gemeinsamen Anfang (kein Cache-Treffer)
            u = await self._single_run(client, "baseline_unique", shared=False)
            s["prefix_compare"] = {"prefix_tokens": self.a.shared_prefix,
                                   "ttft_shared": s["ttft_p50"], "ttft_unique": u["ttft_p50"]}
            log(f"  Gemeinsamer Anfang: Wartezeit {fmt(s['ttft_p50'], 3)}s statt "
                f"{fmt(u['ttft_p50'], 3)}s ohne")
        self.summary["baseline"] = s
        log(f"  Wartezeit {fmt(s['ttft_p50'], 3)}s · Tempo {fmt(s['user_tps_p50'], 1)} tok/s "
            f"· Fehler {s['errors']}")
        await self.probe_alone(client)

    # ── 2. Immer mehr gleichzeitig ──────────────────────────────────────────
    async def _ramp_level(self, client, c, fine=False):
        self.mon.phase = f"ramp_c{c}"
        a = self.a
        log(f"  {c:>4} gleichzeitig{' (Feinsuche)' if fine else ''}: "
            f"{a.level_seconds:.0f}s messen …")
        c0 = await self.counters()
        async with self.probing(client, "ramp", f"{c} gleichzeitig", c):
            res, w0, w1 = await run_timed(client, self.job, c, a.level_seconds, a.warmup_seconds,
                                          a.min_samples, a.level_seconds * a.max_level_factor)
        s = summarize_timed(res, w0, w1, c, slo=(a.slo_ttft, a.slo_user_tps))
        self.counter_delta(c0, await self.counters(), s)
        s["client_lag_ms"] = self.lag_ms(w0, w1)
        s["fine"] = fine
        self.save_raw("ramp", res, level=c)
        log(f"      → {fmt(s['out_tps'], 0)} tok/s gesamt · {fmt(s['user_tps_p50'], 1)} tok/s "
            f"pro Person · Wartezeit p95 {fmt(s['ttft_p95'], 2)}s · Stocken p95 "
            f"{fmt(s['stall_p95'], 2)}s · Fehler {s['error_rate'] * 100:.0f}% · "
            f"{s['n_window']} Messungen"
            + (f" · {s['preemptions']} verdrängt" if s.get("preemptions") else ""))
        return s

    def _break_reason(self, s):
        if s["error_rate"] > self.a.max_error_rate:
            return f"zu viele Fehler: {s['error_rate'] * 100:.0f} %"
        if s["ttft_p95"] and s["ttft_p95"] > self.a.break_ttft:
            return f"Wartezeit über {self.a.break_ttft:.0f} s"
        if s["ok"] == 0:
            return "keine Antwort mehr"
        return None

    def _saturated(self, steps):
        """Leistung wächst über zwei Stufen kaum noch und die Ziele sind schon verfehlt –
        höhere Stufen würden nur lange dauern, aber nichts Neues zeigen."""
        f = self.a.saturation_stop
        if f <= 0 or len(steps) < 3:
            return False
        t = [x["out_tps"] or 0 for x in steps[-3:]]
        flat = t[1] < t[0] * (1 + f) and t[2] < t[1] * (1 + f)
        cfg = self.summary["config"]
        missed = not any(meets_slo(x, cfg["slo_ttft"], cfg["slo_user_tps"]) for x in steps[-2:])
        return flat and missed

    async def ramp(self, client):
        log("━━ 2/6 Immer mehr gleichzeitig (Concurrency-Ramp) ━━")
        levels = sorted({int(x) for x in self.a.levels.split(",") if x.strip()})
        steps, break_info, saturated = [], None, None

        def publish():
            steps.sort(key=lambda x: x["concurrency"])
            self.summary["ramp"] = {"steps": steps, "break": break_info, "saturated": saturated}
            self.notify()

        for c in levels:
            if self.server_down:
                break
            s = await self._ramp_level(client, c)
            steps.append(s)
            reason = None
            if s["error_types"].get("verbindung") and await self.check_crash(client, f"bei {c} gleichzeitig"):
                reason = "Server abgestürzt"
            reason = reason or self._break_reason(s)
            if reason:
                break_info = {"concurrency": c, "reason": reason}
                log(f"  ✗ Bruchpunkt erreicht: {reason}")
            elif c != levels[-1] and self._saturated(steps):
                saturated = c
                log("  ■ Leistung steigt nicht mehr und die Ziele sind verfehlt – höhere Stufen "
                    "werden übersprungen.")
            publish()
            if reason or saturated:
                break

        # Feinsuche: genaue Grenze zwischen letzter guter und erster schlechter Stufe
        cfg = self.summary["config"]
        for _ in range(self.a.fine_steps):
            if self.server_down:
                break
            good = [s["concurrency"] for s in steps if meets_slo(s, cfg["slo_ttft"], cfg["slo_user_tps"])]
            if not good:
                break
            g = max(good)
            worse = [s["concurrency"] for s in steps if s["concurrency"] > g]
            if not worse:
                break
            b = min(worse)
            if b - g < 2 or b / g < 1.2:
                break
            mid = int(round((g + b) / 2))
            if mid in {s["concurrency"] for s in steps}:
                break
            s = await self._ramp_level(client, mid, fine=True)
            steps.append(s)
            if s["error_types"].get("verbindung"):
                await self.check_crash(client, f"Feinsuche bei {mid}")
            publish()
        publish()

    # ── 3. Echter Andrang (offene Last) ─────────────────────────────────────
    def _rates(self):
        """Ankunftsraten in Fragen pro Sekunde. 'auto' = Anteile der höchsten Rate, die die
        Ramp geschafft hat (ohne Ramp: grobe Schätzung aus der Baseline)."""
        spec = str(self.a.rates or "auto").strip().lower()
        if spec != "auto":
            return sorted({float(x) / 60 for x in spec.split(",") if x.strip() and float(x) > 0})
        steps = (self.summary.get("ramp") or {}).get("steps") or []
        top = max((s.get("req_s") or 0 for s in steps), default=0)
        if not top:
            base = self.summary.get("baseline") or {}
            top = 4 / base["e2e_p50"] if base.get("e2e_p50") else 0
        if not top:
            return []

        def nice(per_min):  # auf zwei wichtige Stellen runden
            e = 10 ** math.floor(math.log10(per_min)) if per_min > 0 else 1
            return round(per_min / e * 10) / 10 * e

        return sorted({nice(top * 60 * f) / 60 for f in (0.25, 0.5, 0.75, 0.9, 1.0, 1.2)})

    async def rate_test(self, client):
        log("━━ 3/6 Echter Andrang (zufällige Ankünfte) ━━")
        a = self.a
        cfg = self.summary["config"]
        rates = self._rates()
        if not rates:
            log("  Übersprungen – keine Rate bestimmbar (erst Ramp oder Baseline laufen lassen).")
            return
        drain = min(a.timeout, max(60.0, a.rate_seconds))
        stages, brk = [], None

        def publish():
            self.summary["rate"] = {"stages": stages, "break": brk, "think_time": a.think_time}
            self.notify()

        for rate in rates:
            if self.server_down:
                break
            self.mon.phase = f"rate_{rate * 60:g}"
            log(f"  {fmt(rate * 60, 1)} Fragen pro Minute (zufällig verteilt): "
                f"{a.rate_seconds:.0f}s …")
            c0 = await self.counters()
            async with self.probing(client, "rate", f"{fmt(rate * 60, 0)} Fragen/min", rate):
                res, w0, w1, max_in, late = await run_rate(client, self.job, rate, a.rate_seconds,
                                                           a.warmup_seconds, drain, self.arrivals)
            s = summarize_timed(res, w0, w1, None, slo=(a.slo_ttft, a.slo_user_tps))
            self.counter_delta(c0, await self.counters(), s)
            inwin = sorted((r for r in res if w0 <= r["tp_start"] < w1), key=lambda r: r["tp_start"])
            s.update(rate=rate, rate_actual=len(inwin) / max(1e-6, w1 - w0), max_inflight=max_in,
                     send_late_ms=late * 1000 if late is not None else None,
                     client_lag_ms=self.lag_ms(w0, w1))
            # Wächst die Schlange? Wartezeit der letzten gegen die ersten Ankünfte
            ok = [r for r in inwin if r["ok"]]
            k = len(ok) // 3
            if k >= 3:
                first = pct([r["ttft"] for r in ok[:k]], 50)
                last = pct([r["ttft"] for r in ok[-k:]], 50)
                s["queue_growth"] = last / first if first else None
                s["overloaded"] = bool(s["queue_growth"] and s["queue_growth"] > 2
                                       and last > cfg["slo_ttft"])
            else:
                s["overloaded"] = s["error_rate"] > a.max_error_rate
            self.save_raw("rate", res, rate=rate)
            stages.append(s)
            log(f"      → Wartezeit p50 {fmt(s['ttft_p50'], 2)}s / p95 {fmt(s['ttft_p95'], 2)}s · "
                f"{fmt(s['user_tps_p50'], 1)} tok/s pro Person · Ziele erfüllt "
                f"{fmt(s.get('goodput_pct'), 0)} % · bis zu {max_in} gleichzeitig"
                + (" · Schlange wächst" if s["overloaded"] else ""))
            reason = None
            if s["error_types"].get("verbindung") and await self.check_crash(
                    client, f"bei {fmt(rate * 60, 1)} Fragen/min"):
                reason = "Server abgestürzt"
            reason = reason or self._break_reason(s) or (
                "die Warteschlange wächst immer weiter" if s["overloaded"] else None)
            if reason:
                brk = {"rate": rate, "reason": reason}
                log(f"  ✗ Überlastet: {reason}")
            publish()
            if reason:
                break
        publish()
        cap_ = capacity(self.summary)
        if cap_.get("users_rate"):
            log(f"  Reicht für ≈ {fmt(cap_['users_rate'], 0)} aktive Nutzer "
                f"(bei {fmt(a.think_time, 0)} s Denkpause zwischen zwei Fragen)")

    # ── 4. Lange Texte ──────────────────────────────────────────────────────
    async def context_sweep(self, client):
        log("━━ 4/6 Lange Texte (Kontext) ━━")
        lengths = sorted({int(x) for x in self.a.context_lengths.split(",") if x.strip()})
        limit = self.a.max_context or self.summary["meta"].get("max_model_len")
        if limit:
            top = int(limit * 0.95) - self.a.context_output_len  # Puffer für Chat-Template
            lengths = [n for n in lengths if n <= top]
            if not lengths or lengths[-1] < top * 0.9:
                lengths.append(top)
        steps, limit_hit = [], None
        for L in lengths:
            if self.server_down:
                break
            self.mon.phase = f"ctx_{L}"
            log(f"  ≈{L:>7} Tokens: einzeln …")
            job = lambda L=L: (self.pf.make(L), self.a.context_output_len)  # noqa: E731
            res1, wall1 = await run_batch(client, job, self.a.context_requests, 1)
            s1 = summarize(res1, wall1)
            self.save_raw("context_single", res1, input_len=L)
            step = {"input_len": L, "single": s1, "parallel": None}
            if s1["ttft_p50"] and s1["in_tokens_avg"]:
                step["prefill_tps"] = s1["in_tokens_avg"] / s1["ttft_p50"]
            if s1["ok"] == 0:
                detail = next((r.get("error_detail", "") for r in res1 if not r["ok"]), "")
                limit_hit = {"input_len": L, "mode": "einzeln",
                             "error": list(s1["error_types"].keys()), "detail": detail[:200]}
                log(f"      ✗ scheitert schon einzeln: {s1['error_types']}")
                steps.append(step)
                if s1["error_types"].get("verbindung"):
                    await self.check_crash(client, f"Kontext {L}")
                break
            log(f"      Wartezeit {fmt(s1['ttft_p50'], 2)}s · Lesetempo "
                f"{fmt(step.get('prefill_tps'), 0)} tok/s")
            cc = self.a.context_concurrency
            if cc > 1:
                log(f"  ≈{L:>7} Tokens: {cc} gleichzeitig …")
                resp_, wallp = await run_batch(client, job, cc, cc)
                sp = summarize(resp_, wallp)
                self.save_raw("context_parallel", resp_, input_len=L)
                step["parallel"] = sp
                log(f"      Wartezeit p95 {fmt(sp['ttft_p95'], 2)}s · Fehler {sp['errors']}/{sp['n']}")
                if sp["error_types"].get("verbindung"):
                    await self.check_crash(client, f"Kontext {L} × {cc}")
                if sp["error_rate"] > self.a.max_error_rate and not limit_hit:
                    limit_hit = {"input_len": L, "mode": f"{cc} gleichzeitig",
                                 "error": list(sp["error_types"].keys())}
            steps.append(step)
            self.summary["context"] = {"steps": steps, "limit": limit_hit, "max_ok": None,
                                       "server_limit": limit}
            self.notify()
        max_ok = max((s["input_len"] for s in steps if s["single"]["ok"] > 0), default=None)
        self.summary["context"] = {"steps": steps, "limit": limit_hit, "max_ok": max_ok,
                                   "server_limit": limit}

    # ── 4. Ansturm ──────────────────────────────────────────────────────────
    async def spike(self, client):
        log("━━ 5/6 Ansturm (Spike) ━━")
        self.mon.phase = "spike_idle"
        await asyncio.sleep(self.a.spike_idle)
        n = self.a.spike_size
        self.mon.phase = "spike"
        log(f"  {n} Fragen auf einmal …")
        t0 = time.perf_counter()
        c0 = await self.counters()
        res, wall = await run_batch(client, self.job, n, n)
        s = summarize(res, wall)
        self.counter_delta(c0, await self.counters(), s)
        s["client_lag_ms"] = self.lag_ms(t0, t0 + wall)
        self.save_raw("spike", res)
        crashed = False
        if s["error_types"].get("verbindung"):
            crashed = await self.check_crash(client, "beim Ansturm")
        ttft_sorted = sorted(r["ttft"] for r in res if r["ok"])
        log(f"  → beantwortet {s['ok']}/{n} · längste Wartezeit {fmt(s['ttft_max'], 1)}s")
        rec = None
        if not self.server_down:
            self.mon.phase = "spike_recovery"
            await asyncio.sleep(3)
            rres, rwall = await run_batch(client, self.fixed_job, 3, 1)
            rec = summarize(rres, rwall)
            self.save_raw("spike_recovery", rres)
        base = self.summary.get("baseline") or {}
        recovered = None
        if rec and rec["ok"] and base.get("ttft_p50"):
            recovered = (rec["ttft_p50"] <= base["ttft_p50"] * 1.5 + 0.05 and
                         (rec["user_tps_p50"] or 0) >= (base["user_tps_p50"] or 0) * 0.8)
        elif rec and rec["ok"]:
            recovered = True
        log(f"  Danach wieder normal: {'ja' if recovered else 'nein/unklar'}")
        self.summary["spike"] = {"size": n, "burst": s, "ttft_sorted": ttft_sorted,
                                 "recovery": rec, "recovered": recovered, "crashed": crashed}

    # ── 5. Ausdauer ─────────────────────────────────────────────────────────
    async def soak(self, client):
        minutes = self.a.soak_minutes
        c = self.a.soak_concurrency
        if not c:
            rec = recommended_concurrency(self.summary, self.a)
            c = max(1, rec or 4)
        log(f"━━ 6/6 Ausdauer (Soak): {fmt(float(minutes), 1)} min bei {c} gleichzeitig ━━")
        self.mon.phase = "soak"
        c0 = await self.counters()
        t0 = time.perf_counter()
        end = t0 + minutes * 60
        results = []

        async def worker():
            while time.perf_counter() < end - 1 and not self.server_down:
                msgs, n_out = self.job()
                r = await client.request(msgs, n_out)
                r["concurrency"] = c
                results.append(r)
                if not r["ok"]:
                    await asyncio.sleep(2)

        async def progress():
            while time.perf_counter() < end and not self.server_down:
                await asyncio.sleep(60)
                now = time.perf_counter()
                recent = [r for r in results if r["tp_start"] > now - 60]
                ok = [r for r in recent if r["ok"]]
                log(f"  … noch {max(0, (end - now) / 60):.0f} min · letzte Minute: "
                    f"{len(ok)} ok, {len(recent) - len(ok)} Fehler, "
                    f"{fmt(window_tps(results, now - 60, now), 0)} tok/s")

        prog = asyncio.create_task(progress())
        async with self.probing(client, "soak", "Ausdauer"):
            await asyncio.gather(*(worker() for _ in range(c)))
        prog.cancel()
        wall = time.perf_counter() - t0
        self.save_raw("soak", results)
        bucket = self.a.soak_bucket
        buckets = []
        nb = max(1, int(minutes * 60 // bucket))
        for i in range(nb):
            b0, b1 = t0 + i * bucket, t0 + (i + 1) * bucket
            started = [r for r in results if b0 <= r["tp_start"] < b1]
            sb = summarize(started, bucket) if started else None
            if sb:
                sb["out_tps"] = window_tps(results, b0, b1)
                sb["client_lag_ms"] = self.lag_ms(b0, b1)
            buckets.append({"t_min": (i + 1) * bucket / 60, "s": sb})
        s = summarize(results, wall)
        self.counter_delta(c0, await self.counters(), s)
        s["out_tps"] = window_tps(results, t0 + min(bucket, wall / 4), t0 + nb * bucket)
        q = max(1, nb // 4)
        skip = 1 if nb > 3 else 0  # erstes Intervall = Anlaufphase
        first = [b["s"] for b in buckets[skip:skip + q] if b["s"]]
        last = [b["s"] for b in buckets[-q:] if b["s"]]
        deg = None
        if first and last:
            f_tps = mean([b["out_tps"] for b in first])
            l_tps = mean([b["out_tps"] for b in last])
            f_ttft = mean([b["ttft_p50"] for b in first])
            l_ttft = mean([b["ttft_p50"] for b in last])
            deg = {"tps_change_pct": (l_tps / f_tps - 1) * 100 if f_tps else None,
                   "ttft_change_pct": (l_ttft / f_ttft - 1) * 100 if f_ttft else None}
        self.summary["soak"] = {"minutes": minutes, "concurrency": c, "total": s,
                                "buckets": buckets, "degradation": deg}
        if deg:
            log(f"  Tempo Anfang → Ende: {fmt(deg['tps_change_pct'], 1)} %")

    # ── 6. Kontrollmessung ──────────────────────────────────────────────────
    async def control(self, client):
        base = self.summary.get("baseline")
        if not base:
            return
        log("━━ Kontrollmessung: noch einmal wie am Anfang ━━")
        self.mon.phase = "control"
        await asyncio.sleep(3)
        s = await self._single_run(client, "control")

        def diff(k):
            return (s[k] / base[k] - 1) * 100 if s.get(k) and base.get(k) else None
        self.summary["control"] = {"s": s, "tps_diff_pct": diff("user_tps_p50"),
                                   "ttft_diff_pct": diff("ttft_p50")}
        log(f"  Tempo {fmt(s['user_tps_p50'], 1)} tok/s (Anfang: {fmt(base['user_tps_p50'], 1)}) "
            f"· Abweichung {fmt(self.summary['control']['tps_diff_pct'], 1)} %")

    # ── Ablauf ──────────────────────────────────────────────────────────────
    async def run(self):
        self.mon.start()
        lag_task = asyncio.create_task(self.lag_watch())
        tests = [t.strip() for t in self.a.tests.split(",")]
        try:
            async with Client(self.a) as client:
                await self.preflight(client)
                plan = [("baseline", self.baseline), ("ramp", self.ramp), ("rate", self.rate_test),
                        ("context", self.context_sweep), ("spike", self.spike),
                        ("soak", self.soak), ("control", self.control)]
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


# ════════════════════════════════════════════════════════════════════════════
#  Wie sehr kann man den Zahlen trauen?
# ════════════════════════════════════════════════════════════════════════════

def assess_quality(summary):
    """Prüft die Messung selbst. Jeder Punkt: Ampel (good/warn/bad/info), kurzer Titel,
    Messwert und eine Erklärung in einfacher Sprache."""
    items = []
    pre = summary.get("prechecks") or {}
    cfg = summary.get("config") or {}
    steps = (summary.get("ramp") or {}).get("steps", [])
    brk = (summary.get("ramp") or {}).get("break")

    def add(status, title, value, text):
        items.append({"status": status, "title": title, "value": value, "text": text})

    busy = pre.get("busy")
    if busy is None:
        add("info", "War der Server am Anfang frei?", "unbekannt",
            "Konnte nicht geprüft werden. Falls gleichzeitig andere den Server benutzt haben, "
            "sehen die Ergebnisse schlechter aus als sie sind.")
    elif busy == 0:
        add("good", "War der Server am Anfang frei?", "ja",
            "Niemand sonst hat den Server beim Start benutzt. Die Messung gehört uns allein.")
    else:
        add("warn", "War der Server am Anfang frei?", f"nein ({busy} fremde Anfragen)",
            "Jemand anderes hat den Server gleichzeitig benutzt. Die Ergebnisse sind "
            "wahrscheinlich etwas zu schlecht.")

    rtt = pre.get("rtt_ms")
    if rtt is not None:
        if rtt < 5:
            add("good", "Netzwerk-Umweg", f"{fmt(rtt, 1)} ms",
                "Der Weg zum Server ist so kurz, dass er die Messung praktisch nicht beeinflusst.")
        elif rtt < 50:
            add("warn" if rtt >= 20 else "good", "Netzwerk-Umweg", f"{fmt(rtt, 0)} ms",
                "Jede Wartezeit enthält diesen kleinen Umweg übers Netzwerk. Für die Bewertung "
                "spielt das kaum eine Rolle.")
        else:
            add("warn", "Netzwerk-Umweg", f"{fmt(rtt, 0)} ms",
                "Das Netzwerk ist langsam (z. B. VPN). Alle Wartezeiten sind um etwa diesen Wert "
                "zu hoch – der Server selbst ist schneller.")

    rate_stages = (summary.get("rate") or {}).get("stages", [])
    lags = [(f"{s['concurrency']} gleichzeitig", s.get("client_lag_ms")) for s in steps
            if s.get("client_lag_ms") is not None]
    lags += [(f"{fmt(s['rate'] * 60, 0)} Fragen/min", s.get("client_lag_ms")) for s in rate_stages
             if s.get("client_lag_ms") is not None]
    if lags:
        worst_c, worst = max(lags, key=lambda x: x[1])
        if worst < 30:
            add("good", "Kam der Messrechner hinterher?", f"ja (max. {fmt(worst, 0)} ms Verzug)",
                "Der Rechner, der die Fragen stellt, war nie überlastet. Er misst also sauber.")
        elif worst < 150:
            add("warn", "Kam der Messrechner hinterher?", f"knapp ({fmt(worst, 0)} ms bei {worst_c})",
                "Bei vielen gleichzeitigen Fragen hatte der Messrechner viel zu tun. Die Wartezeiten "
                "auf den höchsten Stufen könnten etwas zu hoch sein.")
        else:
            add("bad", "Kam der Messrechner hinterher?", f"nein ({fmt(worst, 0)} ms bei {worst_c})",
                "Der Messrechner war überlastet. Die Werte auf den höchsten Stufen sind zu "
                "schlecht – der Server kann mehr. Besser von einem stärkeren Rechner testen.")

    lates = [s["send_late_ms"] for s in rate_stages if s.get("send_late_ms") is not None]
    if lates:
        worst = max(lates)
        st = "good" if worst < 50 else "warn" if worst < 250 else "bad"
        add(st, "Kamen die zufälligen Fragen pünktlich?", f"max. {fmt(worst, 0)} ms zu spät",
            {"good": "Beim Test „Echter Andrang“ hat der Messrechner jede Frage zum geplanten "
                     "Zeitpunkt losgeschickt.",
             "warn": "Einige Fragen gingen etwas verspätet los. Die tatsächliche Menge pro Minute "
                     "war dadurch leicht kleiner als geplant.",
             "bad": "Der Messrechner kam mit dem Losschicken nicht hinterher. Die Ergebnisse von "
                    "„Echter Andrang“ sind zu gut – besser von einem stärkeren Rechner testen."}[st])

    if pre.get("usage") is not None:
        if pre.get("usage"):
            add("good", "Zählt der Server die Wörter selbst?", "ja",
                "Die Anzahl der Wortstücke (Tokens) kommt direkt vom Server und ist exakt.")
        else:
            add("warn", "Zählt der Server die Wörter selbst?", "nein",
                "Der Server meldet keine Zahlen. Die Wortstücke werden geschätzt – Tempo-Angaben "
                "können um etwa 10–20 % daneben liegen.")

    fl = pre.get("fixed_length")
    if cfg.get("length_mix") == "mixed":
        add("info", "Waren alle Antworten gleich lang?", "absichtlich gemischt",
            "Fragen und Antworten waren mal kurz, mal lang – wie im Alltag. Das ist realistischer, "
            "die Stufen schwanken dadurch aber etwas mehr.")
    elif fl is not None:
        if fl:
            add("good", "Waren alle Antworten gleich lang?", "ja",
                "Jede Antwort hatte genau dieselbe Länge. So sind alle Stufen fair vergleichbar.")
        else:
            add("warn", "Waren alle Antworten gleich lang?", "nein",
                "Der Server beendet Antworten selbst, sie sind unterschiedlich lang. Vergleiche "
                "zwischen den Stufen sind dadurch etwas ungenauer.")

    ns = [s.get("n_window", s["n"]) for s in steps if not (brk and brk["concurrency"] == s["concurrency"])]
    if ns:
        mn = min(ns)
        st = "good" if mn >= 20 else "warn" if mn >= 10 else "bad"
        add(st, "Genug Messungen pro Stufe?", f"mind. {mn} je Stufe",
            {"good": "Jede Stufe hat genug Antworten, damit einzelne Ausreißer nicht ins Gewicht fallen.",
             "warn": "Einige Stufen haben wenige Antworten. Die Zahlen stimmen grob, können aber "
                     "etwas schwanken. Für mehr Sicherheit den vollständigen Test nehmen.",
             "bad": "Zu wenige Antworten pro Stufe – einzelne Ausreißer können das Ergebnis "
                    "stark verschieben. Messzeit pro Stufe erhöhen."}[st])

    stab = [(s["concurrency"], s.get("stability_pct")) for s in steps
            if s.get("stability_pct") is not None and not (brk and brk["concurrency"] == s["concurrency"])]
    if stab:
        c, worst = max(stab, key=lambda x: x[1])
        st = "good" if worst < 15 else "warn" if worst < 35 else "bad"
        add(st, "Lief jede Stufe gleichmäßig?", f"max. {fmt(worst, 0)} % Schwankung",
            {"good": "Innerhalb jeder Stufe blieb die Leistung ruhig. Die Werte sind stabil.",
             "warn": f"Bei {c} gleichzeitig schwankte die Leistung spürbar. Der Wert dort ist "
                     "ein Mittelwert aus unruhigen Messungen.",
             "bad": f"Bei {c} gleichzeitig schwankte die Leistung stark. Vielleicht hat der "
                    "Server nebenbei etwas anderes gemacht."}[st])

    ctl = summary.get("control")
    if ctl and ctl.get("tps_diff_pct") is not None:
        d = abs(ctl["tps_diff_pct"])
        st = "good" if d < 10 else "warn" if d < 25 else "bad"
        add(st, "Gleiches Ergebnis am Ende wie am Anfang?", f"{fmt(ctl['tps_diff_pct'], 1)} %",
            {"good": "Die Kontrollmessung am Ende passt zum Anfang. Die Ergebnisse sind wiederholbar.",
             "warn": "Am Ende war der Server etwas anders schnell als am Anfang – z. B. durch "
                     "Wärme oder andere Nutzer. Die Zahlen gelten mit etwas Vorsicht.",
             "bad": "Am Ende war der Server deutlich anders als am Anfang. Etwas hat sich während "
                    "des Tests verändert (Hitze, andere Nutzer, Neustart?)."}[st])

    crashes = summary.get("crashes") or []
    if crashes:
        add("bad", "Ist der Server abgestürzt?", f"ja ({len(crashes)}×)",
            "Der Server war zwischendurch nicht erreichbar. Das ist selbst ein wichtiges "
            "Ergebnis – die Werte danach sind aber mit Vorsicht zu lesen.")
    else:
        add("good", "Ist der Server abgestürzt?", "nein", "Der Server war die ganze Zeit erreichbar.")

    if pre.get("thinking"):
        base = summary.get("baseline") or {}
        tc = base.get("ttfc_p50")
        add("info", "Denkt das Modell vor der Antwort?", "ja",
            "Das Modell überlegt erst im Stillen. Die Wartezeit zählt bis zum ersten Denk-Wort, "
            "das Tempo zählt die Denk-Wörter mit."
            + (f" Bis die eigentliche Antwort beginnt, dauert es ohne Andrang {fmt(tc, 1)} s."
               if tc is not None else
               " Innerhalb der eingestellten Antwortlänge kam das Modell oft gar nicht über das "
               "Nachdenken hinaus – Antwortlänge erhöhen oder Nachdenken abschalten."))

    pr = summary.get("probes")
    if pr:
        n = pr["n_alone"] + pr["n_load"]
        if pr.get("alone_pct") is not None and pr["alone_pct"] < 75:
            add("warn", "Taugen die Kontrollfragen für dieses Modell?", f"allein nur {fmt(pr['alone_pct'], 0)} % richtig",
                "Schon ohne Last beantwortet das Modell viele Kontrollfragen falsch (z. B. weil es zu "
                "ausführlich antwortet oder vorher zu lange nachdenkt). Der Vergleich unter Last ist "
                "trotzdem aussagekräftig, der absolute Wert nicht.")
        elif pr["n_load"] < 20:
            add("info", "Genug Kontrollfragen unter Last?", f"{pr['n_load']} Stück",
                "Nur wenige Kontrollfragen liefen unter Last. Ein einzelner Ausreißer verschiebt den "
                "Prozentwert stark – im gründlichen Test sind es deutlich mehr.")
        else:
            add("good", "Genug Kontrollfragen?", f"{n} Stück",
                "Genug Kontrollfragen, um zu sehen, ob die Antworten unter Last schlechter werden.")

    sts = [i["status"] for i in items]
    overall = "niedrig" if "bad" in sts else "mittel" if sts.count("warn") >= 2 else "hoch"
    return {"overall": overall, "items": items}


def build_report(summary, path, a=None):
    """PowerPoint-Bericht (siehe report_pptx.py)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from report_pptx import build_report as _build
    if "quality" not in summary:
        summary["quality"] = assess_quality(summary)
    return _build(summary, path)


def build_pdf_report(summary, path):
    """Einseitiger PDF-Bericht (siehe report_pdf.py). Ohne reportlab wird er übersprungen."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from report_pdf import build_pdf
    except ImportError:
        log("  PDF übersprungen – dafür fehlt reportlab (python -m pip install reportlab).")
        return None
    if "quality" not in summary:
        summary["quality"] = assess_quality(summary)
    return build_pdf(summary, path)


def build_comparison(dirs, path, labels=None):
    """Vergleichsbericht aus mehreren Ergebnisordnern (siehe report_compare.py)."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from report_compare import build_compare
    summaries = []
    for d in dirs:
        with open(os.path.join(d, "summary.json"), encoding="utf-8") as f:
            s = json.load(f)
        s.setdefault("quality", assess_quality(s))
        summaries.append(s)
    return build_compare(summaries, path, labels)


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def build_parser():
    p = argparse.ArgumentParser(description="LLM-Härtetest mit PowerPoint-Bericht",
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--version", action="version", version=f"LAST {VERSION}")
    g = p.add_argument_group("Server")
    g.add_argument("--base-url", default=os.environ.get("LLMST_BASE_URL", "http://localhost:8000/v1"),
                   help="OpenAI-kompatible Basis-URL (vLLM :8000, SGLang :30000, "
                        "llama.cpp :8080, Ollama :11434)")
    g.add_argument("--model", default=None, help="Modellname (Standard: erstes aus /v1/models)")
    g.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    g.add_argument("--metrics-url", default=None,
                   help="Prometheus-/metrics-URL (Standard: automatisch, 'off' zum Abschalten)")
    g.add_argument("--timeout", type=float, default=300, help="Timeout pro Anfrage (s)")
    g.add_argument("--no-ignore-eos", action="store_true",
                   help="Kein ignore_eos senden (Ausgabelänge dann variabel)")
    g.add_argument("--disable-thinking", action="store_true",
                   help="Qwen3: Thinking-Modus über chat_template_kwargs abschalten")

    g = p.add_argument_group("Tests")
    g.add_argument("--tests", default="baseline,ramp,rate,context,spike,soak")
    g.add_argument("--input-len", type=int, default=1024, help="Eingabe-Tokens (Standard)")
    g.add_argument("--output-len", type=int, default=256, help="Ausgabe-Tokens (Standard)")
    g.add_argument("--length-mix", choices=["fixed", "mixed"], default="fixed",
                   help="mixed = Längen schwanken wie im Alltag (log-normal um input/output-len)")
    g.add_argument("--shared-prefix", type=int, default=0,
                   help="So viele Tokens gemeinsamer System-Prompt vor jeder Frage "
                        "(misst den Nutzen des Prefix-Caches; 0 = aus)")
    g.add_argument("--seed", type=int, default=None,
                   help="Zufallszahl für wiederholbare Texte (Standard: zufällig, wird gespeichert)")
    g.add_argument("--baseline-requests", type=int, default=10,
                   help="Fragen beim Test 'Einer allein' und bei der Kontrollmessung")
    g.add_argument("--levels", default="1,2,4,8,16,32,64,128,256",
                   help="Stufen: so viele Fragen gleichzeitig")
    g.add_argument("--level-seconds", type=float, default=60, help="Messzeit pro Stufe (s)")
    g.add_argument("--warmup-seconds", type=float, default=10,
                   help="Anlaufzeit pro Stufe, die nicht mitzählt (s)")
    g.add_argument("--min-samples", type=int, default=40,
                   help="Mindestens so viele Antworten pro Stufe (Messzeit verlängert sich)")
    g.add_argument("--max-level-factor", type=float, default=4,
                   help="Messzeit pro Stufe höchstens × diesen Faktor verlängern")
    g.add_argument("--fine-steps", type=int, default=2,
                   help="Zwischenstufen, um die genaue Grenze zu finden")
    g.add_argument("--saturation-stop", type=float, default=0.05,
                   help="Ramp beenden, wenn der Durchsatz zwei Stufen lang um weniger als diesen "
                        "Anteil wächst und die Ziele verfehlt sind (0 = aus)")
    g.add_argument("--rates", default="auto",
                   help="Echter Andrang: Fragen pro Minute, mit Komma (auto = aus der Ramp)")
    g.add_argument("--rate-seconds", type=float, default=60,
                   help="Echter Andrang: Messzeit pro Rate (s)")
    g.add_argument("--think-time", type=float, default=60,
                   help="Denkpause eines aktiven Nutzers zwischen zwei Fragen (s) – für die "
                        "Umrechnung in Nutzerzahlen")
    g.add_argument("--context-lengths", default="512,2048,8192,16384,32768,65536,131072")
    g.add_argument("--context-requests", type=int, default=3,
                   help="Fragen pro Textlänge (einzeln)")
    g.add_argument("--context-output-len", type=int, default=64)
    g.add_argument("--context-concurrency", type=int, default=4,
                   help="Zusätzlich so viele lange Anfragen parallel (1 = aus)")
    g.add_argument("--max-context", type=int, default=None,
                   help="Kontextlimit, falls der Server es nicht meldet")
    g.add_argument("--spike-size", type=int, default=64)
    g.add_argument("--spike-idle", type=float, default=10)
    g.add_argument("--soak-minutes", type=float, default=15)
    g.add_argument("--soak-concurrency", type=int, default=0,
                   help="0 = automatisch die empfohlene Parallelität")
    g.add_argument("--soak-bucket", type=float, default=60, help="Auflösung Soak-Diagramm (s)")
    g.add_argument("--cooldown", type=float, default=5, help="Pause zwischen den Tests (s)")
    g.add_argument("--recovery-wait", type=float, default=120,
                   help="So lange auf Server-Neustart nach Absturz warten (s)")

    g = p.add_argument_group("Antwortqualität")
    g.add_argument("--probe-interval", type=float, default=5,
                   help="Während der Lasttests alle so viele Sekunden eine Kontrollfrage (0 = aus)")
    g.add_argument("--probe-count", type=int, default=12,
                   help="Kontrollfragen ohne Last als Vergleichswert")
    g.add_argument("--probe-thinking-tokens", type=int, default=1024,
                   help="Antwortlänge der Kontrollfragen bei Modellen, die erst nachdenken")

    g = p.add_argument_group("Wirtschaftlichkeit (Annahmen für die Kostenrechnung)")
    g.add_argument("--target-users", type=int, default=0,
                   help="So viele sollen ihn zu Spitzenzeiten gleichzeitig aktiv nutzen (0 = unbekannt)")
    g.add_argument("--hw-price", type=float, default=ECON_DEFAULTS["hw_price"],
                   help="Anschaffungspreis des Servers (€)")
    g.add_argument("--amort-months", type=int, default=ECON_DEFAULTS["amort_months"],
                   help="Abschreibung über so viele Monate")
    g.add_argument("--server-watts", type=float, default=ECON_DEFAULTS["server_watts"],
                   help="Stromverbrauch des Servers unter Last (W)")
    g.add_argument("--power-price", type=float, default=ECON_DEFAULTS["power_price"],
                   help="Strompreis (€/kWh)")
    g.add_argument("--cloud-price-in", type=float, default=ECON_DEFAULTS["cloud_price_in"],
                   help="Cloud-Vergleich: Preis pro Million Eingabe-Tokens (€)")
    g.add_argument("--cloud-price-out", type=float, default=ECON_DEFAULTS["cloud_price_out"],
                   help="Cloud-Vergleich: Preis pro Million Ausgabe-Tokens (€)")
    g.add_argument("--work-hours", type=float, default=ECON_DEFAULTS["work_hours"],
                   help="Nutzungsstunden pro Monat (Arbeitszeit)")

    g = p.add_argument_group("Grenzwerte")
    g.add_argument("--slo-ttft", type=float, default=2.0, help="Ziel: TTFT p95 (s)")
    g.add_argument("--slo-user-tps", type=float, default=10.0, help="Ziel: tok/s pro Nutzer")
    g.add_argument("--break-ttft", type=float, default=60.0, help="Bruch: TTFT p95 über (s)")
    g.add_argument("--max-error-rate", type=float, default=0.05, help="Bruch: Fehlerquote über")

    g = p.add_argument_group("Ausgabe")
    g.add_argument("--out", default=None, help="Ergebnisordner")
    g.add_argument("--monitor-interval", type=float, default=2.0)
    g.add_argument("--local-monitor", choices=["auto", "on", "off"], default="auto",
                   help="GPU/RAM dieses Rechners aufzeichnen (auto = nur wenn der Server "
                        "auf localhost läuft)")
    g.add_argument("--quick", action="store_true",
                   help="Schnelldurchlauf (~15 min): weniger Stufen, kürzere Messungen")
    g.add_argument("--report-only", metavar="ORDNER",
                   help="Nur die Präsentation aus einem vorhandenen Ergebnisordner neu bauen")
    g.add_argument("--compare", metavar="ORDNER", nargs="+",
                   help="Vergleichsbericht aus zwei oder mehr Ergebnisordnern bauen")
    g.add_argument("--labels", default=None,
                   help="Namen für --compare, mit Komma (z. B. 'vorher,nachher')")
    return p


QUICK_PROFILE = {"levels": "1,4,16,32,64", "level_seconds": 30, "warmup_seconds": 5,
                 "min_samples": 20, "fine_steps": 1, "context_lengths": "1024,8192,32768",
                 "context_requests": 2, "spike_size": 32, "soak_minutes": 3, "soak_bucket": 20,
                 "baseline_requests": 5, "rate_seconds": 30, "probe_count": 8}


def apply_quick(a, p):
    """Schnellprofil: nur Werte ändern, die nicht explizit gesetzt wurden."""
    if a.quick:
        for k, v in QUICK_PROFILE.items():
            if getattr(a, k) == p.get_default(k):
                setattr(a, k, v)
    return a


def parse_args():
    p = build_parser()
    return apply_quick(p.parse_args(), p)


def main():
    a = parse_args()
    if a.compare:
        if len(a.compare) < 2:
            sys.exit("--compare braucht mindestens zwei Ergebnisordner.")
        labels = [x.strip() for x in a.labels.split(",")] if a.labels else None
        out = a.out or os.path.join(RESULTS_ROOT, "LLM-Haertetest-Vergleich.pptx")
        build_comparison(a.compare, out, labels)
        log(f"Vergleich: {out}")
        return
    if a.report_only:
        with open(os.path.join(a.report_only, "summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
        for k in ("slo_ttft", "slo_user_tps"):
            if k in summary.get("config", {}):
                setattr(a, k, summary["config"][k])
        out = os.path.join(a.report_only, "LLM-Haertetest.pptx")
        build_report(summary, out, a)
        log(f"Präsentation: {out}")
        if build_pdf_report(summary, os.path.join(a.report_only, "LLM-Haertetest.pdf")):
            log(f"Kurzbericht: {os.path.join(a.report_only, 'LLM-Haertetest.pdf')}")
        return
    outdir = a.out or os.path.join(RESULTS_ROOT, f"results_{dt.datetime.now():%Y%m%d_%H%M}")
    os.makedirs(outdir, exist_ok=True)
    log(f"Ergebnisse → {outdir}/")
    st = StressTest(a, outdir)
    try:
        asyncio.run(st.run())
    except PreflightError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        log("Abgebrochen.")
        st.save_summary()
    out = os.path.join(outdir, "LLM-Haertetest.pptx")
    build_report(st.summary, out, a)
    log(f"Fertig. Präsentation: {out}")
    pdf = build_pdf_report(st.summary, os.path.join(outdir, "LLM-Haertetest.pdf"))
    if pdf:
        log(f"Kurzbericht (1 Seite A4): {pdf}")


if __name__ == "__main__":
    main()
