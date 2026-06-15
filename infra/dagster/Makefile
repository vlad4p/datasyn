# Dagster runtime stack. ENVIRONMENT=dev|prod. User code: ../datasyn-code or stub.

DATASYN_ROOT := $(abspath ../..)
COMPOSE_FILE := $(DATASYN_ROOT)/infra/dagster/docker-compose.yaml
STACK_ENV_FILE := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/.env)
include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../deploy.mk)

DATASYN_CODE_DIR ?= $(abspath $(DATASYN_ROOT)/../datasyn-code)
DATASYN_USER_CODE_STUB_DIR := $(abspath $(DATASYN_ROOT)/infra/dagster/user_code)
DATASYN_CODE_BUILD_DIR := $(if $(wildcard $(DATASYN_CODE_DIR)/Dockerfile),$(DATASYN_CODE_DIR),$(DATASYN_USER_CODE_STUB_DIR))
export DATASYN_CODE_DIR := $(DATASYN_CODE_BUILD_DIR)

# Absolute host path for DockerRunLauncher bind mounts (entrypoint + patch-runtime).
ifeq ($(strip $(DATASYN_DATA_LOCAL_HOST)),)
  export DATASYN_DATA_LOCAL_HOST := $(abspath $(DATASYN_ROOT)/data-local)
endif

DEPLOY_COMPOSE = DATASYN_IMAGE_PREFIX="$(DATASYN_IMAGE_PREFIX)" DATASYN_IMAGE_TAG="$(DATASYN_IMAGE_TAG)" \
	DATASYN_IMAGE_NAMESPACE="$(DATASYN_IMAGE_NAMESPACE)" DATASYN_CODE_DIR="$(DATASYN_CODE_DIR)" \
	docker compose

.PHONY: help build up down ps logs restart user-code-build patch-runtime pull

help:
	@echo "infra/dagster — ENVIRONMENT=$(ENVIRONMENT) prefix=$(DATASYN_IMAGE_PREFIX)"
	@echo "  make bootstrap | print-env | patch-runtime | build | up | down | ps | logs | restart | pull"
	@echo "  make user-code-build   # dagster_user_code_image (datasyn-code or stub)"

patch-runtime:
	@bash "$(abspath $(dir $(lastword $(MAKEFILE_LIST))))/scripts/patch-dagster-yaml.sh"

user-code-build: bootstrap
	$(call deploy_echo_env)
	@if [ "$(DATASYN_CODE_BUILD_DIR)" = "$(DATASYN_USER_CODE_STUB_DIR)" ]; then \
	  echo "[dagster] datasyn-code not found — stub $(DATASYN_USER_CODE_STUB_DIR)"; \
	  docker build -t "$(DATASYN_IMAGE_PREFIX)/dagster_user_code_image:$(DATASYN_IMAGE_TAG)" \
	    -f "$(DATASYN_USER_CODE_STUB_DIR)/Dockerfile" "$(DATASYN_USER_CODE_STUB_DIR)"; \
	else \
	  $(MAKE) -C "$(DATASYN_CODE_DIR)" build ENVIRONMENT="$(ENVIRONMENT)"; \
	fi

build: user-code-build patch-runtime
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" build

pull: bootstrap patch-runtime
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" pull

up: bootstrap patch-runtime
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(MAKE) user-code-build
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d --build
else
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" pull
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d --force-recreate
endif

down:
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" down

ps:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" ps

logs:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" logs --tail=100

restart:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" restart
