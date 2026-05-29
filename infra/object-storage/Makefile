# Object storage (MinIO + storage-mcp). Same targets as root; set ENVIRONMENT=dev|prod.

DATASYN_ROOT := $(abspath ../..)
SERVICE_COMPOSE := $(DATASYN_ROOT)/infra/object-storage/docker-compose.yaml
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help build up down ps logs

help:
	@echo "infra/object-storage — ENVIRONMENT=$(ENVIRONMENT) prefix=$(DATASYN_IMAGE_PREFIX)"
	@echo "  make build | up | down | ps | logs"

build: deploy-service-build

up: deploy-service-up

down: deploy-service-down

ps: deploy-service-ps

logs: deploy-service-logs
