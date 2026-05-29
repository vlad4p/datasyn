# DuckDB warehouse + duckdb-mcp (+ optional UI profile). ENVIRONMENT=dev|prod.

DATASYN_ROOT := $(abspath ../..)
SERVICE_COMPOSE := $(DATASYN_ROOT)/infra/duckdb/docker-compose.yaml
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help build up down ps logs ui-up ui-down

help:
	@echo "infra/duckdb — ENVIRONMENT=$(ENVIRONMENT) prefix=$(DATASYN_IMAGE_PREFIX)"
	@echo "  make build | up | down | ps | logs"
	@echo "  make ui-up | ui-down   # DuckDB Local UI (profile ui; locks warehouse file)"

build: deploy-service-build

up: deploy-service-up

down: deploy-service-down

ps: deploy-service-ps

logs: deploy-service-logs

ui-up: bootstrap
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" --profile ui up -d --build duckdb-ui

ui-down:
	-$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" --profile ui stop duckdb-ui
