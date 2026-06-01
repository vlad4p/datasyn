# Datasyn wrapper for optional Langfuse (upstream clone in ../langfuse/, gitignored).
# Pulls public images — not part of DATASYN_IMAGE_PREFIX / ENVIRONMENT=dev|prod.

DATASYN_ROOT := $(abspath ../..)
LANGFUSE_DIR := $(DATASYN_ROOT)/infra/langfuse
COMPOSE_FILE := $(LANGFUSE_DIR)/docker-compose.yml
ENV_EXAMPLE := $(abspath .)/.env.datasyn.example
ENV_FILE := $(LANGFUSE_DIR)/.env

.PHONY: help init-env check-clone up down ps logs

help:
	@echo "Langfuse (optional) — clone upstream into infra/langfuse/ first:"
	@echo "  git clone https://github.com/langfuse/langfuse.git $(LANGFUSE_DIR)"
	@echo ""
	@echo "  make init-env   # cp .env.datasyn.example → infra/langfuse/.env"
	@echo "  make up         # docker compose up -d"
	@echo "  make down | ps | logs"
	@echo ""
	@echo "  UI → http://127.0.0.1:3000"
	@echo "  Then set LANGFUSE_* in $(DATASYN_ROOT)/.env and restart brain (make brain-restart)."

check-clone:
	@test -f "$(COMPOSE_FILE)" || { \
	  echo "[langfuse] missing $(COMPOSE_FILE)"; \
	  echo "  git clone https://github.com/langfuse/langfuse.git $(LANGFUSE_DIR)"; \
	  exit 1; \
	}

init-env: check-clone
	@test -f "$(ENV_FILE)" || cp "$(ENV_EXAMPLE)" "$(ENV_FILE)"
	@echo "[langfuse] wrote $(ENV_FILE) — edit if needed, then: make up"

up: init-env
	docker compose -f "$(COMPOSE_FILE)" --env-file "$(ENV_FILE)" up -d
	@echo ""
	@echo "[langfuse] UI → http://127.0.0.1:3000"
	@echo "[langfuse] login: admin@example.com / datasyn-local (from .env.datasyn.example)"
	@echo "[langfuse] Add LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY to $(DATASYN_ROOT)/.env"

down: check-clone
	docker compose -f "$(COMPOSE_FILE)" --env-file "$(ENV_FILE)" down

ps: check-clone
	docker compose -f "$(COMPOSE_FILE)" --env-file "$(ENV_FILE)" ps

logs: check-clone
	docker compose -f "$(COMPOSE_FILE)" --env-file "$(ENV_FILE)" logs --tail=100 -f
