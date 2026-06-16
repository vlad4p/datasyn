# Datasyn — minimal Makefile
#
#   make agent-dev              # uv brain + npm Vite (local)
#   make build-agent            # Docker image brain
#   make build-ui               # Docker image ui
#   make push                   # push brain + ui
#   make push agent             # push brain only
#   make push ui                # push ui only

SHELL := /bin/bash
DATASYN_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
COMPOSE_FILE := $(DATASYN_ROOT)/docker-compose.yaml
UV ?= uv

ifneq ($(wildcard $(DATASYN_ROOT)/.env),)
  include $(DATASYN_ROOT)/.env
  export
endif

DATASYN_IMAGE_NAMESPACE ?= datasyn
DATASYN_IMAGE_TAG ?= latest
DATASYN_IMAGE_REGISTRY ?=
# Fleet VMs are amd64; set linux/arm64 only for local compose on Apple Silicon.
DATASYN_DOCKER_PLATFORM ?= linux/amd64
export DOCKER_DEFAULT_PLATFORM := $(DATASYN_DOCKER_PLATFORM)

# host:port only (strip http(s):// if pasted from a browser URL)
ifneq ($(DATASYN_IMAGE_REGISTRY),)
  DATASYN_IMAGE_REGISTRY := $(shell printf '%s' '$(DATASYN_IMAGE_REGISTRY)' | sed -E 's|^https?://||; s|/.*$$||')
endif

ifeq ($(DATASYN_IMAGE_REGISTRY),)
  DATASYN_IMAGE_PREFIX := $(DATASYN_IMAGE_NAMESPACE)
else
  DATASYN_IMAGE_PREFIX := $(DATASYN_IMAGE_REGISTRY)/$(DATASYN_IMAGE_NAMESPACE)
endif

# PREFIX may also come from .env — never allow a scheme in image names
DATASYN_IMAGE_PREFIX := $(shell printf '%s' '$(DATASYN_IMAGE_PREFIX)' | sed -E 's|^https?://||')

export DATASYN_IMAGE_PREFIX DATASYN_IMAGE_TAG DATASYN_IMAGE_NAMESPACE

API_PORT ?= 8002
export API_PORT
VITE_PROXY_TARGET ?= http://127.0.0.1:$(API_PORT)
export VITE_PROXY_TARGET

COMPOSE := DATASYN_IMAGE_PREFIX="$(DATASYN_IMAGE_PREFIX)" DATASYN_IMAGE_TAG="$(DATASYN_IMAGE_TAG)" \
	DATASYN_IMAGE_NAMESPACE="$(DATASYN_IMAGE_NAMESPACE)" docker compose

# make push agent | make push ui  (agent → compose service brain)
PUSH_SELECTION := $(filter agent ui,$(MAKECMDGOALS))

.PHONY: agent-dev build-ui build-agent push agent ui _agent-dev-brain _agent-dev-ui _push-images

agent-dev:
	@command -v $(UV) >/dev/null 2>&1 || { echo "uv not found"; exit 1; }
	@command -v npm >/dev/null 2>&1 || { echo "npm not found"; exit 1; }
	cd "$(DATASYN_ROOT)" && $(UV) sync
	cd "$(DATASYN_ROOT)/ui" && npm install
	@$(MAKE) -j2 _agent-dev-brain _agent-dev-ui

_agent-dev-brain:
	@echo "[brain] http://127.0.0.1:$(API_PORT)"
	cd "$(DATASYN_ROOT)" && $(UV) run brain-dev

_agent-dev-ui:
	@echo "[ui] http://127.0.0.1:5173 → $(VITE_PROXY_TARGET)"
	cd "$(DATASYN_ROOT)/ui" && npm run dev

build-ui:
	@echo "$(DATASYN_IMAGE_PREFIX)/ui:$(DATASYN_IMAGE_TAG)"
	$(COMPOSE) -f "$(COMPOSE_FILE)" build ui

build-agent:
	@echo "$(DATASYN_IMAGE_PREFIX)/brain:$(DATASYN_IMAGE_TAG)"
	$(COMPOSE) -f "$(COMPOSE_FILE)" build brain

push:
	@$(MAKE) _push-images SERVICES="$(if $(PUSH_SELECTION),$(PUSH_SELECTION),agent ui)"

# Swallow service names so `make push agent` does not fail on unknown target
agent ui:
	@:

_push-images:
	@set -euo pipefail; \
	if [ -z "$(DATASYN_IMAGE_REGISTRY)" ]; then \
	  echo "Set DATASYN_IMAGE_REGISTRY in .env"; exit 1; \
	fi; \
	for name in $(SERVICES); do \
	  svc="$$name"; \
	  build_target="$$name"; \
	  [ "$$name" = agent ] && svc=brain && build_target=agent; \
	  img="$(DATASYN_IMAGE_PREFIX)/$$svc:$(DATASYN_IMAGE_TAG)"; \
	  if ! docker image inspect "$$img" >/dev/null 2>&1; then \
	    local_tag="$(DATASYN_IMAGE_NAMESPACE)/$$svc:$(DATASYN_IMAGE_TAG)"; \
	    alt=$$(docker images --format '{{.Repository}}:{{.Tag}}' "$(DATASYN_IMAGE_PREFIX)/$$svc" 2>/dev/null | head -1 || true); \
	    if [ -z "$$alt" ] && docker image inspect "$$local_tag" >/dev/null 2>&1; then \
	      alt="$$local_tag"; \
	    fi; \
	    if [ -n "$$alt" ]; then \
	      echo "tag $$alt -> $$img"; \
	      docker tag "$$alt" "$$img"; \
	    else \
	      echo "missing $$img — run: make build-$$build_target"; exit 1; \
	    fi; \
	  fi; \
	  echo "push $$img"; \
	  if command -v skopeo >/dev/null 2>&1; then \
	    skopeo copy "docker-daemon:$$img" "docker://$$img" --dest-tls-verify=false; \
	  else \
	    $(COMPOSE) -f "$(COMPOSE_FILE)" push "$$svc"; \
	  fi; \
	done
