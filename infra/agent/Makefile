# Brain + UI containers (root docker-compose.yaml). ENVIRONMENT=dev|prod.

DATASYN_ROOT := $(abspath ../..)
COMPOSE_FILE := $(DATASYN_ROOT)/docker-compose.yaml
include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../deploy.mk)

.PHONY: help build up down ps logs

help:
	@echo "infra/agent — brain + UI containers  ENVIRONMENT=$(ENVIRONMENT)"
	@echo "  Host ports: brain :8002  ui :8003"
	@echo "  make bootstrap | print-env | build | up | down | ps | logs"
	@echo ""
	@echo "Daily dev uses host uv + npm instead: make agent-dev (repo root)"

build: bootstrap
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" build

up: bootstrap
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d --build
else
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" pull
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d
endif

down:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" down

ps:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" ps

logs:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" logs --tail=100
