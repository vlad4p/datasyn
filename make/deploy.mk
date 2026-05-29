# Shared deploy logic for datasyn (root + infra/* + datasyn-code).
# Include from a Makefile after setting DATASYN_ROOT (repo root abspath).
#
#   ENVIRONMENT=dev   — local ``docker compose build``; image prefix ``datasyn/…``; no registry
#   ENVIRONMENT=prod  — ``docker compose pull``; prefix ``<registry>/datasyn/…``; build/push via ``publish``

ifndef DATASYN_DEPLOY_MK_INCLUDED
DATASYN_DEPLOY_MK_INCLUDED := 1

SHELL := /bin/bash

# --- Environment gate ---
ENVIRONMENT ?= dev
ifeq ($(filter dev prod,$(ENVIRONMENT)),)
$(error ENVIRONMENT must be dev or prod (got '$(ENVIRONMENT)'))
endif

# Repo root (set by includer before ``include``)
DATASYN_ROOT ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
DATASYN_MK_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# --- Image naming (compose: ``${DATASYN_IMAGE_PREFIX}/<service>:${DATASYN_IMAGE_TAG}``) ---
DATASYN_IMAGE_NAMESPACE ?= datasyn
DATASYN_IMAGE_TAG ?= latest

DATASYN_IMAGE_REGISTRY ?=
REGISTRY_PUBLISH_PORT ?= 5000
REGISTRY_HTTP_URL ?= http://10.13.10.119:5000
DOCKER_PLATFORM_REMOTE ?= linux/amd64
SKOPEO_IMAGE ?= quay.io/skopeo/stable:latest
STORAGE_MCP_BUILDX_BUILDER ?= datasyn-registry-push

ifeq ($(ENVIRONMENT),dev)
  DATASYN_IMAGE_PREFIX := $(DATASYN_IMAGE_NAMESPACE)
  DEPLOY_USE_REGISTRY := 0
else
  ifeq ($(DATASYN_IMAGE_REGISTRY),)
    DATASYN_IMAGE_REGISTRY := $(shell printf '%s' "$(REGISTRY_HTTP_URL)" | sed -E 's|^https?://||; s|/.*||')
  endif
  ifeq ($(DATASYN_IMAGE_REGISTRY),)
    $(error ENVIRONMENT=prod: set DATASYN_IMAGE_REGISTRY=host:port or REGISTRY_HTTP_URL)
  endif
  DATASYN_IMAGE_PREFIX := $(DATASYN_IMAGE_REGISTRY)/$(DATASYN_IMAGE_NAMESPACE)
  DEPLOY_USE_REGISTRY := 1
endif

export ENVIRONMENT DATASYN_IMAGE_PREFIX DATASYN_IMAGE_NAMESPACE DATASYN_IMAGE_TAG
export DOCKER_REGISTRY := $(DATASYN_IMAGE_PREFIX)

# --- Compose paths (root Makefile may override before include) ---
INFRA_OBJECT_STORAGE_COMPOSE ?= $(DATASYN_ROOT)/infra/object-storage/docker-compose.yaml
INFRA_DUCKDB_COMPOSE ?= $(DATASYN_ROOT)/infra/duckdb/docker-compose.yaml
INFRA_DAGSTER_COMPOSE ?= $(DATASYN_ROOT)/infra/dagster/docker-compose.yaml
INFRA_DISTRIBUTION_COMPOSE ?= $(DATASYN_ROOT)/infra/distribution/docker-compose.yaml
ROOT_COMPOSE ?= $(DATASYN_ROOT)/docker-compose.yaml

SHARED_NETWORK ?= infra-datasynk
SHARED_VOLUMES ?= duckdb_data storage

# --- Dagster user code ---
DATASYN_CODE_DIR ?= $(abspath $(DATASYN_ROOT)/../datasyn-code)
DATASYN_USER_CODE_STUB_DIR := $(abspath $(DATASYN_ROOT)/infra/dagster/user_code)
DATASYN_CODE_BUILD_DIR := $(if $(wildcard $(DATASYN_CODE_DIR)/Dockerfile),$(DATASYN_CODE_DIR),$(DATASYN_USER_CODE_STUB_DIR))
export DATASYN_CODE_DIR := $(DATASYN_CODE_BUILD_DIR)

BUILDKIT_CFG := $(DATASYN_ROOT)/infra/distribution/buildkit-registry-insecure.toml

# --- Helpers ---
DEPLOY_COMPOSE = DATASYN_IMAGE_PREFIX="$(DATASYN_IMAGE_PREFIX)" DATASYN_IMAGE_TAG="$(DATASYN_IMAGE_TAG)" \
	DATASYN_IMAGE_NAMESPACE="$(DATASYN_IMAGE_NAMESPACE)" DATASYN_CODE_DIR="$(DATASYN_CODE_DIR)" \
	docker compose

define deploy_echo_env
	@echo "[deploy] ENVIRONMENT=$(ENVIRONMENT) DATASYN_IMAGE_PREFIX=$(DATASYN_IMAGE_PREFIX)"
endef

.PHONY: deploy-print-env bootstrap registry-up registry-down

deploy-print-env:
	$(call deploy_echo_env)

bootstrap:
	@docker network inspect "$(SHARED_NETWORK)" >/dev/null 2>&1 || docker network create "$(SHARED_NETWORK)"
	@for v in $(SHARED_VOLUMES); do \
		docker volume inspect "$$v" >/dev/null 2>&1 || docker volume create "$$v"; \
	done

registry-up: bootstrap
	$(DEPLOY_COMPOSE) -f "$(INFRA_DISTRIBUTION_COMPOSE)" up -d

registry-down:
	-$(DEPLOY_COMPOSE) -f "$(INFRA_DISTRIBUTION_COMPOSE)" down

# --- Per-compose targets (used by infra/*/Makefile via ``SERVICE_COMPOSE``) ---

# Build one stack compose file (``make -C infra/duckdb build``).
deploy-service-build:
	@test -n '$(SERVICE_COMPOSE)' || (echo 'Set SERVICE_COMPOSE in infra/*/Makefile' >&2; exit 1)
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" build

deploy-service-up:
	@test -n '$(SERVICE_COMPOSE)' || (echo 'Set SERVICE_COMPOSE in infra/*/Makefile' >&2; exit 1)
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(MAKE) -C "$(DATASYN_ROOT)" bootstrap
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" up -d --build
else
	$(MAKE) -C "$(DATASYN_ROOT)" bootstrap
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" pull
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" up -d
endif

deploy-service-down:
	@test -n '$(SERVICE_COMPOSE)' || (echo 'Set SERVICE_COMPOSE in infra/*/Makefile' >&2; exit 1)
	-$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" down

deploy-service-ps:
	@test -n '$(SERVICE_COMPOSE)' || (echo 'Set SERVICE_COMPOSE in infra/*/Makefile' >&2; exit 1)
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" ps

deploy-service-logs:
	@test -n '$(SERVICE_COMPOSE)' || (echo 'Set SERVICE_COMPOSE in infra/*/Makefile' >&2; exit 1)
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" logs --tail=100

# --- Full-stack image lifecycle (root Makefile) ---

deploy-dagster-user-code-build:
	$(call deploy_echo_env)
	@if [ "$(DATASYN_CODE_BUILD_DIR)" = "$(DATASYN_USER_CODE_STUB_DIR)" ]; then \
	  echo "[dagster] datasyn-code not found — stub $(DATASYN_USER_CODE_STUB_DIR)"; \
	  docker build -t "$(DATASYN_IMAGE_PREFIX)/dagster_user_code_image:$(DATASYN_IMAGE_TAG)" \
	    -f "$(DATASYN_USER_CODE_STUB_DIR)/Dockerfile" "$(DATASYN_USER_CODE_STUB_DIR)"; \
	else \
	  $(MAKE) -C "$(DATASYN_CODE_DIR)" build ENVIRONMENT="$(ENVIRONMENT)"; \
	fi

deploy-images-build: bootstrap deploy-dagster-user-code-build
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" build
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui build
	$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" build
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" build

deploy-images-push: bootstrap deploy-images-build
	$(call deploy_echo_env)
	@test "$(DEPLOY_USE_REGISTRY)" = "1" || { echo "images-push: use ENVIRONMENT=prod"; exit 1; }
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" push
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui push
	$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" push
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" push brain ui

deploy-images-pull: bootstrap
	$(call deploy_echo_env)
	@test "$(DEPLOY_USE_REGISTRY)" = "1" || { echo "images-pull: use ENVIRONMENT=prod"; exit 1; }
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" pull
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui pull
	$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" pull
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" pull

deploy-images-push-skopeo:
	@test "$(DEPLOY_USE_REGISTRY)" = "1" || { echo "images-push-skopeo: use ENVIRONMENT=prod"; exit 1; }
	@cd "$(DATASYN_ROOT)" && set -euo pipefail; \
	_prefix="$(DATASYN_IMAGE_PREFIX)"; \
	push_img() { \
	  img="$$1"; echo "Pushing $$img (skopeo)..."; \
	  dockermount=(); [ -d "$${HOME}/.docker" ] && dockermount=(-v "$${HOME}/.docker:/root/.docker:ro"); \
	  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "$${dockermount[@]}" \
	    "$(SKOPEO_IMAGE)" copy --dest-tls-verify=false "docker-daemon:$$img" "docker://$$img"; \
	}; \
	for f in "$(INFRA_OBJECT_STORAGE_COMPOSE)" "$(INFRA_DUCKDB_COMPOSE)" "$(INFRA_DAGSTER_COMPOSE)" "$(ROOT_COMPOSE)"; do \
	  for img in $$(DATASYN_IMAGE_PREFIX="$$_prefix" docker compose -f "$$f" config --images 2>/dev/null | sort -u); do \
	    [ -n "$$img" ] && push_img "$$img"; \
	  done; \
	done

deploy-infra-up: bootstrap
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(MAKE) -C "$(DATASYN_ROOT)" deploy-images-build ENVIRONMENT=dev
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" up -d
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" up -d
	$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" up -d
else
	$(MAKE) -C "$(DATASYN_ROOT)" deploy-images-pull ENVIRONMENT=prod \
		DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" up -d
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" up -d
	$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" up -d
endif

deploy-agent-up: bootstrap
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" up -d --build
else
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" pull
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" up -d
endif

deploy-mcp-up: bootstrap
	$(call deploy_echo_env)
ifeq ($(ENVIRONMENT),dev)
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" up -d --build minio storage-mcp
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" up -d --build duckdb duckdb-mcp
else
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" pull minio storage-mcp
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" pull duckdb duckdb-mcp
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" up -d minio storage-mcp
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" up -d duckdb duckdb-mcp
endif

endif # DATASYN_DEPLOY_MK_INCLUDED
