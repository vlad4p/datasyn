# Object storage (MinIO + storage-mcp). ENVIRONMENT=dev|prod.

DATASYN_ROOT := $(abspath ../..)
COMPOSE_FILE := $(DATASYN_ROOT)/infra/object-storage/docker-compose.yaml
include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../deploy.mk)

.PHONY: help build up down ps logs mcp-up mcp-down init-bucket

help:
	@echo "infra/object-storage — ENVIRONMENT=$(ENVIRONMENT) prefix=$(DATASYN_IMAGE_PREFIX)"
	@echo "  make bootstrap | print-env | init-bucket | build | up | down | ps | logs"
	@echo "  make mcp-up | mcp-down   # minio + storage-mcp only"

init-bucket:
	@bash "$(abspath $(dir $(lastword $(MAKEFILE_LIST))))/scripts/init-minio-bucket.sh"

build: bootstrap
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" build

up: bootstrap
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d --build
	@$(MAKE) init-bucket
else
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" pull
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d
	@$(MAKE) init-bucket
endif

down:
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" down

ps:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" ps

logs:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" logs --tail=100

mcp-up: bootstrap
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d --build minio storage-mcp
else
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" pull minio storage-mcp
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d minio storage-mcp
endif

mcp-down:
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" stop storage-mcp
