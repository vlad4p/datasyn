# LiteLLM proxy + Postgres. ENVIRONMENT=dev|prod (upstream images).

DATASYN_ROOT := $(abspath ../..)
COMPOSE_FILE := $(DATASYN_ROOT)/infra/litellm/docker-compose.yaml
include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../deploy.mk)

.PHONY: help build up down ps logs init-env

help:
	@echo "infra/litellm — ENVIRONMENT=$(ENVIRONMENT)"
	@echo "  Proxy → http://127.0.0.1:4000  (Postgres host :5434)"
	@echo "  make init-env   # cp .env.example → .env (once)"
	@echo "  make bootstrap | print-env | up | down | ps | logs"
	@echo ""
	@echo "  Nginx edge (optional): see nginx-edge/AGENT_UPSTREAM.md"

init-env:
	@test -f .env || cp .env.example .env
	@echo "[litellm] wrote .env — edit API keys, then: make up"

build: bootstrap
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" build

up: bootstrap init-env
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d --build
else
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" pull
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d
endif

down:
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" down

ps:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" ps

logs:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" logs --tail=100
