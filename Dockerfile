# LLM-Härtetest – Backend (Testlogik) für die Weboberfläche in web/ und die Kommandozeile.
# Läuft auf Windows, macOS (Intel und Apple Silicon) und Linux (x86 und ARM).
#
# Zwei Ziele (docker-compose.yml wählt über BACKEND_TARGET, Standard: browser):
#   slim     – KI-Server, Websites, HTTP-APIs                       (~300 MB)
#   browser  – zusätzlich Abläufe mit unsichtbarem Chromium (Playwright)   (~2 GB)
#
#   docker compose up --build                          → http://localhost:8090
#   BACKEND_TARGET=slim docker compose up --build      → ohne Browser
#
# Details: LIESMICH.md, Abschnitt „Mit Docker“.

# ── Gemeinsame Basis ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

# Schrift mit ≈, → und € für den PDF-Bericht; Zeitzonen für richtige Uhrzeiten in den Berichten
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-browser.txt ./

# Ohne Root-Rechte laufen; der Ergebnisordner ist für jede Benutzerkennung beschreibbar,
# damit docker-compose die Kennung des eigenen Benutzers setzen kann (LOCAL_UID/LOCAL_GID).
RUN useradd --create-home --uid 1000 tester \
 && mkdir -p /app/results && chmod 777 /app/results

# „localhost“ ist im Container der Container selbst – der eigene Rechner heißt host.docker.internal.
ENV TZ=Europe/Berlin \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLMST_IN_DOCKER=1 \
    LLMST_RESULTS=/app/results \
    LLMST_BASE_URL=http://host.docker.internal:8000/v1

EXPOSE 8090
VOLUME /app/results
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8090/api/state', timeout=3)"]
CMD ["python", "stresstest_web.py", "--host", "0.0.0.0", "--port", "8090", "--results", "/app/results"]

# ── slim: ohne Browser ───────────────────────────────────────────────────────
FROM base AS slim
RUN pip install --no-cache-dir -r requirements.txt
COPY VERSION llm_stresstest.py web_stresstest.py flow_stresstest.py flow_recorder.py report_web.py report_pptx.py \
     report_pdf.py report_compare.py stresstest_web.py stresstest_ui.html LIESMICH.md ./
USER tester

# ── browser: mit Chromium für Abläufe ────────────────────────────────────────
FROM base AS browser
# Der Browser schreibt seine Arbeitsdateien nach /tmp (das Dateisystem ist sonst schreibgeschützt).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    XDG_CONFIG_HOME=/tmp \
    XDG_CACHE_HOME=/tmp
RUN pip install --no-cache-dir -r requirements-browser.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY VERSION llm_stresstest.py web_stresstest.py flow_stresstest.py flow_recorder.py report_web.py report_pptx.py \
     report_pdf.py report_compare.py stresstest_web.py stresstest_ui.html LIESMICH.md ./
USER tester
