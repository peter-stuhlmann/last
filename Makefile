# LAST – Lasttest für KI-Server, Websites, HTTP-APIs und Abläufe
#
#   make            zeigt diese Hilfe
#   make up         startet alles          → http://localhost:8090
#   make down       beendet alles
#
# Braucht: Docker (Desktop) und GNU make. Windows ohne make:
#   winget install ezwinports.make      (oder: choco install make)
# Für die Tests der Oberfläche (make test-web, make e2e) zusätzlich Node.js.

# make up SLIM=1  → Backend ohne Browser (kleineres Image, keine Abläufe)
ifdef SLIM
export BACKEND_TARGET = slim
endif

COMPOSE     := docker compose
E2E_COMPOSE := $(COMPOSE) -p last-e2e -f docker-compose.yml -f docker-compose.e2e.yml
IMAGE       := llm-stresstest
URL         := http://localhost:8090

# Git Bash unter Windows würde /src in einen Windows-Pfad verwandeln – abschalten.
export MSYS_NO_PATHCONV = 1

.DEFAULT_GOAL := help
.PHONY: help up build rebuild down restart status logs logs-web logs-backend open \
        test lint test-web check e2e e2e-up e2e-down test-all shell results update clean

help: ## diese Übersicht
	@awk 'BEGIN {FS = ":.*## "; printf "\nBefehle:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2} END {print ""}' $(MAKEFILE_LIST)

# ── Container ──────────────────────────────────────────────────────────────

up: ## starten (baut beim ersten Mal) → http://localhost:8090 · ohne Browser: make up SLIM=1
	$(COMPOSE) up -d --wait
	@echo "LAST läuft: $(URL)"

build: ## Images neu bauen, ohne zu starten
	$(COMPOSE) build

rebuild: ## nach Änderungen am Code: neu bauen und neu starten
	$(COMPOSE) up -d --build --wait
	@echo "LAST läuft: $(URL)"

down: ## beenden (Ergebnisse in results/ bleiben erhalten)
	$(COMPOSE) down

restart: ## Container neu starten, ohne neu zu bauen
	$(COMPOSE) restart

status: ## laufen die Container? sind sie gesund?
	$(COMPOSE) ps

logs: ## Protokoll beider Container live mitlesen (Strg+C beendet nur das Mitlesen)
	$(COMPOSE) logs -f --tail=100

logs-web: ## nur die Oberfläche
	$(COMPOSE) logs -f --tail=100 web

logs-backend: ## nur die Testlogik
	$(COMPOSE) logs -f --tail=100 backend

open: ## Oberfläche im Browser öffnen
	@cmd //c start $(URL) 2>/dev/null || xdg-open $(URL) 2>/dev/null || open $(URL)

shell: ## Kommandozeile im Backend-Container (z. B. für llm_stresstest.py --help)
	$(COMPOSE) run --rm backend sh

results: ## die letzten Läufe in results/ zeigen
	@ls -1dt results/results_* 2>/dev/null | head -10 || echo "noch keine Läufe"

update: ## neuesten Stand holen und neu bauen
	git pull --ff-only
	$(MAKE) rebuild

# ── Prüfen ─────────────────────────────────────────────────────────────────

test: ## Python-Tests im Docker-Image (Lasttest, Berichte, Aufzeichnung mit Chromium)
	$(COMPOSE) build backend
	docker run --rm --tmpfs /tmp -v "$(CURDIR)":/src -w /src $(IMAGE) python -m unittest discover -s tests

lint: ## Python-Lint (ruff) – dieselben Regeln wie in der CI
	docker run --rm -v "$(CURDIR)":/src -w /src python:3.12-slim sh -c "pip install -q ruff && ruff check ."

test-web: ## Tests der Oberfläche (Vitest, inkl. Barrierefreiheit)
	cd web && npm test

check: ## Typen und Lint der Oberfläche
	cd web && npm run typecheck && npm run lint

e2e-up: ## zweite, getrennte Instanz für die Durchlauf-Tests starten (Port 8099)
	$(E2E_COMPOSE) up -d --build --wait

e2e-down: ## Durchlauf-Instanz samt ihren Ergebnissen entfernen
	$(E2E_COMPOSE) down -v

e2e: ## Durchlauf-Tests im echten Browser (startet und entfernt die Instanz selbst)
	$(MAKE) e2e-up
	cd web && npx playwright test; status=$$?; cd .. && $(MAKE) e2e-down; exit $$status

test-all: lint test test-web check e2e ## alles prüfen

# ── Aufräumen ──────────────────────────────────────────────────────────────

clean: ## Container, lokale Images und Build-Reste entfernen – results/ bleibt
	-$(E2E_COMPOSE) down -v --rmi local --remove-orphans
	$(COMPOSE) down --rmi local --remove-orphans
	docker builder prune -f
	rm -rf web/.next web/test-results web/playwright-report __pycache__ tests/__pycache__
