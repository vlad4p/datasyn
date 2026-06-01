# DuckDB warehouse + duckdb-mcp (+ optional UI profile). ENVIRONMENT=dev|prod.

DATASYN_ROOT := $(abspath ../..)
COMPOSE_FILE := $(DATASYN_ROOT)/infra/duckdb/docker-compose.yaml
include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../deploy.mk)

.PHONY: help build up down ps logs ui-up ui-down mcp-up mcp-down

help:
	@echo "infra/duckdb — ENVIRONMENT=$(ENVIRONMENT) prefix=$(DATASYN_IMAGE_PREFIX)"
	@echo "  make bootstrap | print-env | build | up | down | ps | logs"
	@echo "  make ui-up | ui-down   # DuckDB Local UI (profile ui; locks warehouse file)"
	@echo "  make mcp-up | mcp-down # duckdb + duckdb-mcp only"

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
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" down

ps:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" ps

logs:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" logs --tail=100

ui-up: bootstrap
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" --profile ui up -d --build duckdb-ui

ui-down:
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" --profile ui stop duckdb-ui

mcp-up: bootstrap
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d --build duckdb duckdb-mcp
else
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" pull duckdb duckdb-mcp
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d duckdb duckdb-mcp
endif

mcp-down:
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" stop duckdb-mcp
