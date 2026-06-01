# Datasyn — brain + UI local development (host uv + Vite).
#
# Docker infra: see infra/README.md — each stack has its own Makefile.

SHELL := /bin/bash
DATASYN_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

API_PORT ?= 8002
export API_PORT
VITE_PROXY_TARGET ?= http://127.0.0.1:$(API_PORT)
export VITE_PROXY_TARGET
UV ?= uv

.PHONY: help uv-sync ui-install test-agent brain-restart \
	agent-brain agent-dev agent-dev-brain agent-dev-ui

help:
	@echo "Datasyn — brain + UI (host development)"
	@echo ""
	@echo "  make uv-sync          # uv sync → .venv"
	@echo "  make ui-install       # npm install in ui/"
	@echo "  make test-agent       # uv run pytest"
	@echo "  make agent-dev        # brain :$(API_PORT) + Vite :5173 (parallel)"
	@echo "  make agent-brain      # brain only (uv run brain-dev)"
	@echo "  make brain-restart    # kill :$(API_PORT) + agent-brain"
	@echo ""
	@echo "Infra (Docker):  infra/README.md"
	@echo "  make -C infra/object-storage help"
	@echo "Full install:    INSTALL.md"

uv-check:
	@command -v $(UV) >/dev/null 2>&1 || { \
	  echo "uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }

uv-sync: uv-check
	cd "$(DATASYN_ROOT)" && $(UV) sync

ui-install:
	@command -v npm >/dev/null 2>&1 || { echo "npm not found. Install Node.js."; exit 1; }
	cd "$(DATASYN_ROOT)/ui" && npm install

test-agent: uv-sync
	cd "$(DATASYN_ROOT)" && $(UV) run pytest tests/ -q

brain-restart: uv-check
	@echo "[brain] stopping listeners on :$(API_PORT) (if any)…"
	-@lsof -ti tcp:$(API_PORT) | xargs kill 2>/dev/null || true
	@sleep 1
	@$(MAKE) agent-brain

agent-brain: uv-sync
	@echo "[brain] uv run brain-dev → http://127.0.0.1:$(API_PORT)"
	cd "$(DATASYN_ROOT)" && $(UV) run brain-dev

agent-dev:
	@$(MAKE) -j2 agent-dev-brain agent-dev-ui

agent-dev-brain: uv-sync
	@echo "[brain] uv run brain-dev → http://127.0.0.1:$(API_PORT)"
	cd "$(DATASYN_ROOT)" && $(UV) run brain-dev

agent-dev-ui:
	@echo "[ui] npm run dev → http://127.0.0.1:5173  proxy /api → $(VITE_PROXY_TARGET)"
	cd "$(DATASYN_ROOT)/ui" && npm run dev
