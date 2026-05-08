# Dagster docker-compose deploy. Run from: live/mvp/dagster
#
# Requires: docker + docker compose plugin on the host.

COMPOSE  ?= docker compose
DATA_DIR ?= /tmp/dagster_data
PYTHON   ?= python3
VENV     ?= .venv
PIP      ?= $(VENV)/bin/pip
PYTEST   ?= $(VENV)/bin/pytest
RUFF     ?= $(VENV)/bin/ruff

.PHONY: help up down restart logs ps build pull clean psql shell-webserver \
        seed-data view-output clean-data \
        venv install test lint

help:
	@echo "Compose targets:"
	@echo "  up               Build (if needed) and start all services in the background"
	@echo "  down             Stop and remove containers and network (keeps DB volume)"
	@echo "  restart          Restart all services"
	@echo "  logs             Tail logs for all services"
	@echo "  ps               List services"
	@echo "  build            Build user-code and dagster images"
	@echo "  pull             Pull base images"
	@echo "  clean            Down + remove DB volume (DESTRUCTIVE)"
	@echo "  psql             Open a psql shell against the Dagster Postgres"
	@echo "  shell-webserver  Open a shell inside the webserver container"
	@echo ""
	@echo "Local data targets:"
	@echo "  seed-data        Copy seed/people.csv to $(DATA_DIR)/input/ (csv_pipeline input)"
	@echo "  view-output      Show $(DATA_DIR)/output/people_processed.csv after a run"
	@echo "  clean-data       Remove $(DATA_DIR) on the host (DESTRUCTIVE)"
	@echo ""
	@echo "Python project targets:"
	@echo "  venv             Create $(VENV)/ virtualenv"
	@echo "  install          Editable-install the ubika_dagster package with dev extras"
	@echo "  test             Run pytest (creates venv + installs if needed)"
	@echo "  lint             Run ruff over src/ and tests/"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

pull:
	$(COMPOSE) pull

clean:
	$(COMPOSE) down -v

psql:
	$(COMPOSE) exec dagster_postgresql psql -U postgres_user -d postgres_db

shell-webserver:
	$(COMPOSE) exec dagster_webserver bash

seed-data:
	mkdir -p $(DATA_DIR)/input $(DATA_DIR)/output
	cp seed/people.csv $(DATA_DIR)/input/people.csv
	@echo "Seeded $(DATA_DIR)/input/people.csv"

view-output:
	@ls -la $(DATA_DIR)/output 2>/dev/null || (echo "No output yet at $(DATA_DIR)/output"; exit 1)
	@echo "--- $(DATA_DIR)/output/people_processed.csv ---"
	@cat $(DATA_DIR)/output/people_processed.csv

clean-data:
	rm -rf $(DATA_DIR)

venv:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -e '.[dev,webserver]'

test: install
	$(PYTEST)

lint: install
	$(RUFF) check src tests
