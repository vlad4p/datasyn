# Included by each infra/*/Makefile (set DATASYN_ROOT before include).

SHELL := /bin/bash

ENVIRONMENT ?= dev
ifeq ($(filter dev prod,$(ENVIRONMENT)),)
$(error ENVIRONMENT must be dev or prod (got '$(ENVIRONMENT)'))
endif

DATASYN_IMAGE_NAMESPACE ?= datasyn
DATASYN_IMAGE_TAG ?= latest
DATASYN_IMAGE_REGISTRY ?=

# Repo-root deploy .env (minimal: DATASYN_IMAGE_REGISTRY, LITELLM_MASTER_KEY).
ifneq ($(DATASYN_ROOT),)
  ROOT_ENV_FILE := $(DATASYN_ROOT)/.env
  ifneq ($(wildcard $(ROOT_ENV_FILE)),)
    include $(ROOT_ENV_FILE)
    export
  endif
endif

# Optional stack .env (set STACK_ENV_FILE in infra/*/Makefile before include).
ifneq ($(STACK_ENV_FILE),)
  ifneq ($(wildcard $(STACK_ENV_FILE)),)
    include $(STACK_ENV_FILE)
    export
  endif
endif

ifneq ($(LITELLM_KEY),)
  export LITELLM_KEY
else
  ifneq ($(LITELLM_MASTER_KEY),)
    export LITELLM_KEY := $(LITELLM_MASTER_KEY)
  endif
endif

REGISTRY_PUBLISH_PORT ?= 5000
REGISTRY_HTTP_URL ?= http://localhost:5000

ifeq ($(ENVIRONMENT),dev)
  ifneq ($(DATASYN_IMAGE_REGISTRY),)
    DATASYN_IMAGE_PREFIX := $(DATASYN_IMAGE_REGISTRY)/$(DATASYN_IMAGE_NAMESPACE)
  else
    DATASYN_IMAGE_PREFIX := $(DATASYN_IMAGE_NAMESPACE)
  endif
else
  ifeq ($(DATASYN_IMAGE_REGISTRY),)
    DATASYN_IMAGE_REGISTRY := $(shell printf '%s' "$(REGISTRY_HTTP_URL)" | sed -E 's|^https?://||; s|/.*||')
  endif
  ifeq ($(DATASYN_IMAGE_REGISTRY),)
    $(error ENVIRONMENT=prod: set DATASYN_IMAGE_REGISTRY=host:port in .env or REGISTRY_HTTP_URL)
  endif
  DATASYN_IMAGE_PREFIX := $(DATASYN_IMAGE_REGISTRY)/$(DATASYN_IMAGE_NAMESPACE)
endif

export ENVIRONMENT DATASYN_IMAGE_PREFIX DATASYN_IMAGE_NAMESPACE DATASYN_IMAGE_TAG
export DOCKER_REGISTRY := $(DATASYN_IMAGE_PREFIX)
ifneq ($(LITELLM_KEY),)
  export LITELLM_KEY
endif
ifneq ($(LITELLM_MASTER_KEY),)
  export LITELLM_MASTER_KEY
endif

SHARED_NETWORK ?= infra-datasynk
SHARED_VOLUMES ?= duckdb_data storage

DEPLOY_COMPOSE = DATASYN_IMAGE_PREFIX="$(DATASYN_IMAGE_PREFIX)" DATASYN_IMAGE_TAG="$(DATASYN_IMAGE_TAG)" \
	DATASYN_IMAGE_NAMESPACE="$(DATASYN_IMAGE_NAMESPACE)" \
	docker compose

define deploy_echo_env
	@echo "[$(notdir $(CURDIR))] ENVIRONMENT=$(ENVIRONMENT) DATASYN_IMAGE_PREFIX=$(DATASYN_IMAGE_PREFIX)"
endef

.PHONY: bootstrap print-env

bootstrap:
	@docker network inspect "$(SHARED_NETWORK)" >/dev/null 2>&1 || docker network create "$(SHARED_NETWORK)"
	@for v in $(SHARED_VOLUMES); do \
		docker volume inspect "$$v" >/dev/null 2>&1 || docker volume create "$$v"; \
	done

print-env: bootstrap
	$(call deploy_echo_env)
