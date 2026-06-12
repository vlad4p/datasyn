# LiteLLM proxy + Postgres. ENVIRONMENT=dev|prod (upstream images).

DATASYN_ROOT := $(abspath ../..)
COMPOSE_FILE := $(DATASYN_ROOT)/infra/litellm/docker-compose.yaml
COMPOSE_LEGACY_CPU := $(DATASYN_ROOT)/infra/litellm/docker-compose.legacy-cpu.yaml
LEGACY_CPU ?= 0
include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../deploy.mk)

COMPOSE_FILES := -f "$(COMPOSE_FILE)"
ifeq ($(LEGACY_CPU),1)
  COMPOSE_FILES += -f "$(COMPOSE_LEGACY_CPU)"
endif

.PHONY: help build up down ps logs init-env

help:
	@echo "infra/litellm — ENVIRONMENT=$(ENVIRONMENT) LEGACY_CPU=$(LEGACY_CPU)"
	@echo "  Proxy → http://127.0.0.1:4000  (Postgres host :5434)"
	@echo "  make init-env   # cp .env.example → .env (once)"
	@echo "  make bootstrap | print-env | build | up | down | ps | logs"
	@echo "  make up LEGACY_CPU=1   # Proxmox / CPU without x86-64-v2"
	@echo ""
	@echo "  Nginx edge (optional): see nginx-edge/AGENT_UPSTREAM.md"

init-env:
	@test -f .env || cp .env.example .env
	@echo "[litellm] wrote .env — edit API keys, then: make up"

build: bootstrap
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) $(COMPOSE_FILES) build

up: bootstrap init-env
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) $(COMPOSE_FILES) up -d --build
else
ifneq ($(LEGACY_CPU),1)
	$(DEPLOY_COMPOSE) $(COMPOSE_FILES) pull
endif
	$(DEPLOY_COMPOSE) $(COMPOSE_FILES) up -d
endif

down:
	-$(DEPLOY_COMPOSE) $(COMPOSE_FILES) down

ps:
	$(DEPLOY_COMPOSE) $(COMPOSE_FILES) ps

logs:
	$(DEPLOY_COMPOSE) $(COMPOSE_FILES) logs --tail=100
