# Brain + UI containers (root docker-compose.yaml). ENVIRONMENT=dev|prod.

DATASYN_ROOT := $(abspath ../..)
SERVICE_COMPOSE := $(DATASYN_ROOT)/docker-compose.yaml
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help build up down ps logs

help:
	@echo "infra/agent — brain + UI containers  ENVIRONMENT=$(ENVIRONMENT)"
	@echo "  Host ports: brain :8002  ui :8003"
	@echo "  make build | up | down | ps | logs"
	@echo ""
	@echo "Daily dev uses host uv + npm instead: make agent-dev (repo root)"

build: bootstrap
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" build

up: deploy-agent-up

down:
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" down

ps:
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" ps

logs:
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" logs --tail=100
