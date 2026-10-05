# LAST – Weboberfläche (Next.js)

Oberfläche für den Lasttest von KI-Servern und Websites. Design: Figma-Datei „email“, Screens „00 · Neuer Test“,
„01 · Test läuft“, „02 · Ergebnis“. Die Testlogik bleibt im Python-Backend (`../stresstest_web.py`);
diese App ist das einzige, was der Browser zu sehen bekommt.

## Starten

Mit Docker (empfohlen), im übergeordneten Ordner:

    docker compose up --build        # → http://localhost:8090

Zum Entwickeln:

    python ../stresstest_web.py      # Backend auf 127.0.0.1:8090
    npm install
    npm run dev                      # Oberfläche auf http://localhost:3000

| Variable | Bedeutung | Standard |
|---|---|---|
| `BACKEND_URL` | Adresse des Python-Backends (nur serverseitig) | `http://127.0.0.1:8090` |
| `ALLOWED_HOSTS` | weitere erlaubte Host-Namen, kommagetrennt | – (nur localhost) |

## Prüfen

    npm test            # Vitest: Logik, API-Routen, Komponenten inkl. axe-Barrierefreiheitsprüfung
    npm run e2e:up      # eigene Docker-Instanz für die Durchlauf-Tests (Port 8099, eigene Ergebnisse)
    npm run e2e         # Playwright: echter Website-Test von der Eingabe bis zum Bericht, Abbruch,
                        # Schutz vor fremden Seiten, axe im echten Browser (inkl. Farbkontrast)
    npm run e2e:down    # Instanz wieder entfernen
    npm run typecheck
    npm run lint
    npm run build

## Aufbau

| Pfad | Inhalt |
|---|---|
| `src/proxy.ts` | Host-Prüfung, CSRF-Schutz, Content Security Policy mit Nonce |
| `src/app/api/*` | schmale, geprüfte Durchreiche zum Backend (Start, Stopp, Ereignisse, Downloads) |
| `src/lib/validation.ts` | erlaubte Eingaben für einen Teststart (zod) |
| `src/lib/derive.ts` | macht aus Messwerten die Aussagen der Oberfläche (Ampel, Prognose, Kosten) |
| `src/components/` | die drei Screens und ihre Bausteine |

## Sicherheit in Kürze

- Der Browser spricht nie direkt mit dem Backend; es hat in Docker keinen offenen Port.
- Schreibende Anfragen nur von der eigenen Seite und nur als JSON (Schutz vor CSRF);
  unbekannte Host-Namen werden abgelehnt (Schutz vor DNS-Rebinding).
- Strenge CSP ohne Inline-Skripte und ohne Inline-Styles; keine Anfragen an fremde Server
  (Schriften liegen im Projekt).
- Der API-Schlüssel steht nie in einer Adresse und wird nicht im Browser gespeichert.
- Es gibt **keinen Login**. Deshalb ist der Port an `127.0.0.1` gebunden. Wer die Seite im Netz
  freigeben will, braucht davor einen Reverse-Proxy mit Anmeldung und TLS.
