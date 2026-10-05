# LLM-Härtetest – Backend (Testlogik) für die Weboberfläche in web/ und die Kommandozeile.
# Läuft auf Windows, macOS (Intel und Apple Silicon) und Linux (x86 und ARM).
#
#   docker compose up --build        → http://localhost:8090
#
# Details: LIESMICH.md, Abschnitt „Mit Docker“.

FROM python:3.12-slim

# Schrift mit ≈, → und € für den PDF-Bericht; Zeitzonen für richtige Uhrzeiten in den Berichten
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# Unsichtbarer Browser für Abläufe (Aufzeichnen von Anmeldung, Chat usw.) – macht das Image ~400 MB größer
RUN pip install --no-cache-dir -r requirements.txt \
 && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY llm_stresstest.py web_stresstest.py flow_stresstest.py flow_recorder.py report_web.py report_pptx.py \
     report_pdf.py report_compare.py stresstest_web.py stresstest_ui.html LIESMICH.md ./

# Ohne Root-Rechte laufen; der Ergebnisordner ist für jede Benutzerkennung beschreibbar,
# damit docker-compose die Kennung des eigenen Benutzers setzen kann (LOCAL_UID/LOCAL_GID).
RUN useradd --create-home --uid 1000 tester \
 && mkdir -p /app/results && chmod 777 /app/results
USER tester

# „localhost“ ist im Container der Container selbst – der eigene Rechner heißt host.docker.internal.
# Der Browser schreibt seine Arbeitsdateien nach /tmp (das Dateisystem ist sonst schreibgeschützt).
ENV TZ=Europe/Berlin \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLMST_IN_DOCKER=1 \
    LLMST_RESULTS=/app/results \
    LLMST_BASE_URL=http://host.docker.internal:8000/v1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    XDG_CONFIG_HOME=/tmp \
    XDG_CACHE_HOME=/tmp

EXPOSE 8090
VOLUME /app/results

CMD ["python", "stresstest_web.py", "--host", "0.0.0.0", "--port", "8090", "--results", "/app/results"]
