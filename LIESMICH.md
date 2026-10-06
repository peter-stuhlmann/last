# LLM-Härtetest

Lasttest für OpenAI-kompatible Modellserver (vLLM, SGLang, llama.cpp, Ollama), Websites, HTTP-APIs und ganze Abläufe
(Anmelden, dann z. B. einen KI-Chat benutzen), mit Weboberfläche
(„LAST“, Next.js) und PowerPoint-Bericht.

## Mit Docker (Windows, macOS, Linux – ohne Python-Installation)

Voraussetzung: Docker Desktop (Windows/macOS) bzw. Docker mit Compose-Plugin (Linux).
Im Ordner mit dieser Datei:

    docker compose up --build        # erster Start baut das Image (~1 min)

Dann im Browser **http://localhost:8090** öffnen. Beenden mit `Strg+C` bzw. `docker compose down`.

Kürzer geht es mit `make` (Windows: `winget install ezwinports.make`):

    make up          # starten → http://localhost:8090
    make down        # beenden
    make rebuild     # nach Änderungen am Code
    make logs        # Protokoll mitlesen
    make test        # alle Prüfungen: make test-all
    make             # zeigt alle Befehle

- **Ergebnisse** (PowerPoint, PDF, Rohdaten) landen im Ordner `results/` neben dieser Datei.
- **Adresse des Modellservers:** Der Spark im Netz wird ganz normal eingetragen
  (`http://spark.buero.lan:8000/v1`). Läuft der Modellserver **auf demselben Rechner** wie Docker,
  heißt er im Container `host.docker.internal` statt `localhost`
  (`http://host.docker.internal:8000/v1`). Auf Linux muss der Modellserver dafür auf `0.0.0.0`
  lauschen, nicht nur auf `127.0.0.1`.
- **Kommandozeile im Container:**

      docker compose run --rm backend python llm_stresstest.py --base-url http://spark.buero.lan:8000/v1 --quick
      docker compose run --rm backend python llm_stresstest.py --compare results/results_A results/results_B

- **Linux:** Damit die Dateien in `results/` dir gehören:
  `LOCAL_UID=$(id -u) LOCAL_GID=$(id -g) docker compose up --build`
- **Zeitzone** ist Europe/Berlin; anders mit `TZ=Europe/Vienna docker compose up`.
- Die Oberfläche ist nur von diesem Rechner aus erreichbar (Port an `127.0.0.1` gebunden),
  weil sie keinen Passwortschutz hat.
- Es laufen zwei Container: `web` (die Oberfläche, Next.js – Details in `web/README.md`) und
  `backend` (die Testlogik in Python, ohne offenen Port). Beide laufen ohne Root-Rechte und mit
  schreibgeschütztem Dateisystem.
- Läuft auf Intel/AMD und ARM (Apple Silicon, auch direkt auf dem DGX Spark).
  GPU-Werte des Rechners selbst misst der Container nicht – Server-Werte kommen wie gewohnt
  über `/metrics`.

## Installation ohne Docker (einmalig, auf dem Rechner, von dem aus getestet wird)

    python -m pip install aiohttp python-pptx reportlab      # Windows (oder: py -m pip …)
    python3 -m pip install aiohttp python-pptx reportlab     # macOS / Linux

Python 3.9 oder neuer. Wichtig: Pakete mit demselben Python installieren, mit dem du
das Skript startest – daher `python -m pip` statt nur `pip`.

## Weboberfläche starten

    python stresstest_web.py        # Windows
    python3 stresstest_web.py       # macOS / Linux

Dann im Browser **http://localhost:8090** öffnen, Server-URL des Spark eintragen
(z. B. `http://spark.buero.lan:8000/v1`), Enter drücken.

- Ergebnisse erscheinen live auf der Seite, am Ende gibt es die PowerPoint zum Download.
- Alle Läufe landen im Ordner `results/` und sind unter „Frühere Läufe“ wieder abrufbar.
- `--host 0.0.0.0` macht die Seite im Netzwerk erreichbar – **ohne Passwortschutz**.

## Ohne Weboberfläche (Kommandozeile)

    python llm_stresstest.py --base-url http://spark.buero.lan:8000/v1 --quick
    python llm_stresstest.py --help

Vergleich zweier Läufe (z. B. vor und nach einer Einstellungsänderung oder Modell A gegen B) –
in der Weboberfläche unter „Frühere Tests“ ankreuzen, oder:

    python llm_stresstest.py --compare results/results_A results/results_B --labels "vorher,nachher"

## Websites testen

In der Oberfläche unter „Was wird getestet?“ **Website** wählen und die Adresse der Seite eintragen.
LAST schickt simulierte Besucher los; jeder lädt die Seite und – wie ein Browser beim ersten Besuch –
die Bilder, Styles und Skripte derselben Website (ohne Cache, mit eigenen Verbindungen).

| Messwert | Bedeutung |
|---|---|
| Ladezeit | bis die Seite samt Dateien vollständig da ist – daran wird das Ziel gemessen (Standard: 3 s) |
| Erste Antwort | bis der Server die ersten Daten schickt |
| Seiten pro Sekunde | wie viele Seitenaufrufe der Server insgesamt schafft |
| Besucher gleichzeitig | Schätzung: Seiten pro Sekunde × (Ladezeit + Pause zwischen zwei Klicks, Standard 30 s) |

- Schritte: Einer allein · Immer mehr gleichzeitig · Echter Andrang · Großer Ansturm · Ausdauer · Kontrolle.
  „Lange Texte“, Kontrollfragen und der Kostenvergleich gibt es nur beim KI-Server.
- **Verlässlichkeit:** Wie beim KI-Server prüft der Test, ob der Messrechner selbst hinterherkam. War er
  überlastet, wären die Ladezeiten zu hoch – das steht dann als Warnung im Urteil, in der Ampel-Liste
  und im Bericht („Verlässlichkeit der Messung“).
- **Nicht gemessen:** Dateien von fremden Servern (Schriften, Karten, Werbung – sie werden nie angefragt)
  und die Zeit, die der Browser zum Darstellen braucht. Es wird genau eine Adresse getestet, kein Klickpfad.
- **Berichte:** Jeder Lauf erzeugt eine PowerPoint (Empfehlung, Vorgehen, alle Schritte mit Diagrammen,
  größte Dateien der Seite, mögliche Ansatzpunkte, Annahmen und Grenzen) und einen Kurzbericht als PDF
  auf einer A4-Seite. Zwei oder mehr Website-Läufe lassen sich unter „Frühere Läufe“ ankreuzen und als
  Vorher-nachher-Bericht vergleichen. Website- und KI-Server-Läufe lassen sich nicht mischen.
- **Nur eigene Websites testen.** Der Start verlangt eine ausdrückliche Bestätigung; der Test gibt sich im
  User-Agent als `LAST-Lasttest` zu erkennen. Für fremde Betreiber sieht ein Lasttest aus wie ein Angriff
  und kann strafbar sein. Läuft die Website bei einem Hoster oder hinter einem CDN, vorher dort Bescheid geben –
  sonst sperrt deren Schutz den Test (oder euch) aus.
- Tests des Website-Moduls: `docker run --rm --tmpfs /tmp -v "$PWD":/src -w /src llm-stresstest python -m unittest discover -s tests`

## HTTP-APIs testen

Unter „Was wird getestet?“ **HTTP-API** wählen, Adresse des Endpunkts eintragen, Methode (GET, POST, PUT,
PATCH, DELETE) und bei Bedarf unter „Weitere Einstellungen“ Kopfzeilen („Name: Wert“ je Zeile, z. B. für die
Anmeldung) und einen Body. Jede simulierte Anfrage ist genau diese Anfrage; die Antwort gilt als richtig,
wenn der Status zur Erwartung passt (Standard „2xx“).

| Messwert | Bedeutung |
|---|---|
| Antwortzeit | bis die Antwort vollständig da ist – daran wird das Ziel gemessen (Standard: 0,5 s) |
| Erste Antwort | bis der Server die ersten Daten schickt |
| Anfragen pro Minute | höchste zufällig verteilte Last, bei der Antwortzeit und Fehlerquote im Ziel bleiben |

- Dieselben Schritte und Berichte wie beim Website-Test; die simulierten Aufrufer halten ihre
  Verbindungen offen (Keep-Alive), wie Programme es tun. Weiterleitungen werden nicht verfolgt.
- **Kopfzeilen-Werte und Body werden nirgends gespeichert** – nicht im Browser, nicht im Ergebnis, nicht im
  Bericht. Dort stehen nur die Namen der Kopfzeilen und die Größe des Bodys.
- **Schreibende Methoden verändern Daten** – hunderte Male pro Minute. Nur gegen eine Testumgebung richten.
- Nur eigene APIs testen; der Start verlangt dieselbe Bestätigung wie beim Website-Test.

## Abläufe testen (Anmelden, dann z. B. einen KI-Chat benutzen)

Für alles, was aus mehreren Schritten besteht oder eine Anmeldung braucht: Unter „Was wird getestet?“
**Ablauf** wählen, die Startseite eintragen (meist die Anmeldeseite) und die Schritte aufschreiben – ein
Schritt je Zeile, so wie ein Mensch es tun würde:

    tippe in "E-Mail" {email}
    tippe in "Passwort" {passwort}
    klicke "Anmelden"
    warte auf Text "Willkommen"
    messen ab hier
    tippe in "Nachricht" "Was ist ein Lasttest?"
    drücke Enter
    warte auf erste Antwort in ".antwort"
    warte bis ".antwort" fertig ist (2 s ruhig)

So funktioniert es: Der Ablauf wird **einmal in einem echten, unsichtbaren Browser** (Chromium) im Container
ausgeführt. Ab „messen ab hier“ wird mitgeschnitten, was die Seite an den Server schickt. Unter Last werden
genau diese Anfragen **ohne Browser** abgespielt – deshalb sind auch hunderte gleichzeitige Nutzer möglich,
ohne dass auf deinem Rechner Browserfenster aufgehen. Veränderliche Werte (etwa eine Chat-ID aus einer
früheren Antwort) erkennt der Test selbst und holt sie bei jeder Wiederholung frisch.

| Schritt | Bedeutung |
|---|---|
| `tippe in "Feld" Text` | Feld = Beschriftung, Platzhaltertext oder CSS-Selektor; `{name}` wird im Formular zum Passwortfeld |
| `klicke "Knopf"` | Knopf, Link oder Selektor |
| `drücke Enter` | oder Tab, Escape … |
| `warte auf Text "…"` / `warte auf "…"` | bis der Text da ist / bis das Element da ist |
| `warte 2 s` | einfach warten |
| `messen ab hier` | ab hier wird mitgeschnitten – genau einmal, danach mindestens ein Schritt |
| `warte auf erste Antwort in "…"` | misst, wann das erste Wort erscheint (bei einem KI-Chat die wichtigste Zahl) |
| `warte bis "…" fertig ist (2 s ruhig)` | fertig, wenn sich der Text so lange nicht mehr ändert |

- Gemessen werden **Antwortzeit** des Ablaufs (Ziel standardmäßig 10 s) und **erste Antwort**; die Kapazität
  wird in **Nutzern gleichzeitig** angegeben, bei standardmäßig 60 s Pause zwischen zwei Durchläufen.
- Der Bericht zeigt die Schritte, **Bildschirmfotos** aus der Aufzeichnung (`schritt_NN.png` im
  Ergebnisordner) und die aufgezeichneten Anfragen. Scheitert ein Schritt, nennt die Fehlermeldung die
  Zeile und legt `schritt_fehler.png` ab.
- **Platzhalter-Werte (Passwörter) und Sitzungs-Cookies werden nirgends gespeichert** – nicht im Browser,
  nicht in `summary.json`, nicht im Bericht. Der aufgezeichnete Plan lebt nur im Arbeitsspeicher des Tests.
- Grenzen: Alle simulierten Nutzer teilen sich **eine Sitzung** (das Konto der Aufzeichnung); Seiten mit
  **Dauerverbindung (WebSocket)** im Messbereich lassen sich so nicht abspielen; die Darstellung im Browser
  wird nicht gemessen. Das Docker-Image ist wegen Chromium rund 2 GB groß.
- Nur eigene Anwendungen testen; der Start verlangt dieselbe Bestätigung wie beim Website-Test.

- **Systemwerte vom Spark (KV-Cache, Warteschlange)** kommen über `/metrics` des Modellservers
  (bei vLLM und SGLang standardmäßig an). GPU-Temperatur/Takt des Spark lassen sich aus der
  Ferne nicht messen – dafür müsste das Skript auf dem Spark selbst laufen.
- Die gemessenen Wartezeiten enthalten die Netzwerklatenz zwischen deinem Rechner und dem Spark.
  Im Büro-LAN ist das vernachlässigbar, über VPN eher nicht.
- Nur gegen eigene Server testen – ein Lasttest sieht für fremde Server aus wie ein Angriff.

## Dateien

| Datei | Zweck |
|---|---|
| `web/` | die Weboberfläche „LAST“ (Next.js, Tailwind) – wird mit Docker gestartet |
| `stresstest_web.py` | Python-Backend: startet Tests, liefert Ergebnisse und Berichte |
| `stresstest_ui.html` | alte, einfache Oberfläche – nur noch beim Start ohne Docker (`python stresstest_web.py`) |
| `web_stresstest.py` | Lasttest für Websites und HTTP-APIs (nutzt die Lastgeneratoren aus `llm_stresstest.py`) |
| `flow_stresstest.py`, `flow_recorder.py` | Abläufe: Schritt-Sprache, Aufzeichnung im Browser (Playwright), Abspielen per HTTP |
| `report_web.py` | PowerPoint, PDF und Vergleichsbericht für Website-, API- und Ablauf-Läufe |
| `tests/` | Tests für Website-, API- und Ablauf-Lasttest und ihre Berichte |
| `llm_stresstest.py` | Testlogik und Prüfung der Messqualität (auch allein nutzbar) |
| `report_pptx.py` | PowerPoint-Bericht in einfacher Sprache |
| `report_pdf.py` | Kurzbericht als PDF auf einer A4-Seite (braucht `reportlab`, sonst wird er übersprungen) |
| `report_compare.py` | Vergleichsbericht aus zwei oder mehr Läufen |
| `docker-compose.e2e.yml` | zweite, getrennte Instanz für die automatischen Durchlauf-Tests (`web/e2e`) |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore` | Container für Windows, macOS und Linux |
| `requirements.txt` | Python-Pakete (für Docker oder `pip install -r requirements.txt`) |

## Was geprüft wird

| Prüfung | Schnell (~15 min) | Gründlich (~50 min) |
|---|---|---|
| Vorab-Checks: Erreichbarkeit, Netzwerk-Umweg, Server frei?, echte Token-Zählung, feste Antwortlänge | ✓ | ✓ |
| 1. Einer allein (mit gleichem Einleitungstext: Vergleich mit/ohne Prefix-Cache) | 5 Fragen | 10 Fragen |
| 2. Immer mehr gleichzeitig | 1, 4, 16, 32, 64 · je 30 s · mind. 20 Antworten | 1 … 256 · je 60 s · mind. 40 Antworten |
| Feinsuche der genauen Grenze | 1 Zwischenstufe | 2 Zwischenstufen |
| 3. Echter Andrang: Fragen kommen zufällig (Poisson), bis die Schlange wächst | je 30 s | je 60 s |
| 4. Lange Texte | 1k, 8k, 32k Tokens | 0,5k … 128k (bis zum Modell-Limit) |
| 5. Großer Ansturm + Erholung | 32 auf einmal | 64 auf einmal |
| 6. Ausdauer | 3 min | 15 min |
| Kontrollmessung am Ende | ✓ | ✓ |
| Laufend: Absturzerkennung, Aufpasser für den Messrechner, Server-Messwerte | ✓ | ✓ |

Jede Stufe wird nur im „eingeschwungenen Zustand“ gemessen: Anlauf- und Auslaufphase zählen nicht.
Nach einer Fehlermeldung wartet jede simulierte Person kurz, bevor sie es erneut versucht –
wie ein echter Nutzer. So wird ein überlasteter Server nicht zusätzlich geflutet.
Bleibt die Gesamtleistung zwei Stufen lang praktisch gleich und sind die Ziele schon verfehlt,
überspringt der Test die höheren Stufen (`--saturation-stop`, 0 = aus).

## Was zusätzlich gemessen wird

- **Aktive Nutzer:** Aus Fragen pro Sekunde und Antwortdauer wird über das Gesetz von Little
  geschätzt, für wie viele Personen der Server reicht. Annahme: `--think-time` Sekunden Pause
  zwischen zwei Fragen einer Person (Standard 60). Bevorzugt aus „Echter Andrang“, sonst aus der Ramp.
- **Ruckeln:** längste Pause zwischen zwei Textstücken einer Antwort (Stocken p95).
- **Ziele erfüllt (Goodput):** Anteil der einzelnen Fragen, die Wartezeit- *und* Tempo-Ziel einhalten.
- **Verdrängungen / Prefix-Cache-Treffer:** aus `/metrics` (vLLM), je Stufe als Differenz.
- **Thinking-Modelle:** Zeit bis zur eigentlichen Antwort nach dem Nachdenken, getrennt ausgewiesen.

## Realistischere Last (optional)

    --length-mix mixed       # Längen schwanken wie im Alltag (viele kurze, einige lange Fragen)
    --shared-prefix 1500     # gleicher System-Prompt vor jeder Frage → misst den Prefix-Cache
    --seed 42                # gleiche Texte wie in einem früheren Lauf (Seed steht in summary.json)
    --rates 30,60,120        # Echter Andrang mit festen Fragen pro Minute statt automatisch

Die PowerPoint endet mit einer **Zusammenfassung auf einer Folie**: geschätzte Nutzerzahl und
alle Ergebnisse als Ampel-Liste.

## Für die Entscheidung

Jeder Lauf erzeugt neben der PowerPoint einen **Kurzbericht als PDF auf einer A4-Seite**:
Urteil in einem Satz, die vier wichtigsten Zahlen, Begründung, zwei Diagramme und alle Ergebnisse
als Ampel-Liste.

- **Empfehlung:** grün / gelb / rot, gemessen am Bedarf (`--target-users`, in der Oberfläche
  „Wie viele sollen ihn gleichzeitig nutzen?“).
- **Kosten:** eigener Server (Abschreibung + Strom) gegen die Cloud für dieselbe Menge an Antworten,
  und ab welcher Auslastung sich der eigene Server lohnt. **Die Standardwerte sind Platzhalter** –
  Kaufpreis, Stromverbrauch, Strompreis und Cloud-Preise vor dem Test eintragen
  (`--hw-price`, `--server-watts`, `--power-price`, `--cloud-price-in`, `--cloud-price-out`).
- **Antwortqualität:** Während der Lasttests laufen nebenher Kontrollfragen mit bekannter Antwort
  (Rechnen, Sortieren, Hauptstädte, JSON-Format). Verglichen wird: richtig ohne Last gegen richtig
  unter Last (`--probe-interval`, 0 = aus).
