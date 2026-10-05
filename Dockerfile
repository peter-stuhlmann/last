# LLM-Härtetest – Weboberfläche und Kommandozeile in einem Container.
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
RUN pip install --no-cache-dir -r requirements.txt

COPY llm_stresstest.py web_stresstest.py report_web.py report_pptx.py report_pdf.py report_compare.py stresstest_web.py \
     stresstest_ui.html LIESMICH.md ./

# Ohne Root-Rechte laufen; der Ergebnisordner ist für jede Benutzerkennung beschreibbar,
# damit docker-compose die Kennung des eigenen Benutzers setzen kann (LOCAL_UID/LOCAL_GID).
RUN useradd --create-home --uid 1000 tester \
 && mkdir -p /app/results && chmod 777 /app/results
USER tester

# „localhost“ ist im Container der Container selbst – der eigene Rechner heißt host.docker.internal
ENV TZ=Europe/Berlin \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLMST_IN_DOCKER=1 \
    LLMST_RESULTS=/app/results \
    LLMST_BASE_URL=http://host.docker.internal:8000/v1

EXPOSE 8090
VOLUME /app/results

CMD ["python", "stresstest_web.py", "--host", "0.0.0.0", "--port", "8090", "--results", "/app/results"]
