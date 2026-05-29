# Dagster runtime stack. ENVIRONMENT=dev|prod. User code: ../datasyn-code or stub.

DATASYN_ROOT := $(abspath ../..)
SERVICE_COMPOSE := $(DATASYN_ROOT)/infra/dagster/docker-compose.yaml
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help build up down ps logs restart user-code-build

help:
	@echo "infra/dagster — ENVIRONMENT=$(ENVIRONMENT) prefix=$(DATASYN_IMAGE_PREFIX)"
	@echo "  make build | up | down | ps | logs | restart"
	@echo "  make user-code-build   # dagster_user_code_image (datasyn-code or stub)"

build: deploy-dagster-user-code-build deploy-service-build

user-code-build: deploy-dagster-user-code-build

up: deploy-dagster-user-code-build deploy-service-up

down: deploy-service-down

ps: deploy-service-ps

logs: deploy-service-logs

restart:
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" restart
