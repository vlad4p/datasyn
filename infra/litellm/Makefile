# LiteLLM proxy + Postgres. ENVIRONMENT=dev|prod (images are upstream pulls).

DATASYN_ROOT := $(abspath ../..)
SERVICE_COMPOSE := $(DATASYN_ROOT)/infra/litellm/docker-compose.yaml
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help build up down ps logs init-env

help:
	@echo "infra/litellm — ENVIRONMENT=$(ENVIRONMENT)"
	@echo "  Proxy → http://127.0.0.1:4000  (Postgres host :5434)"
	@echo "  make init-env   # cp .env.example → .env (once)"
	@echo "  make up | down | ps | logs"
	@echo ""
	@echo "  Nginx edge (optional): see nginx-edge/AGENT_UPSTREAM.md"

init-env:
	@test -f .env || cp .env.example .env
	@echo "[litellm] wrote .env — edit API keys, then: make up"

build: deploy-service-build

up: init-env deploy-service-up

down: deploy-service-down

ps: deploy-service-ps

logs: deploy-service-logs
