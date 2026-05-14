SHELL := /bin/bash

# Repository root (this Makefile lives at the project root).
MAKEFILE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# Local dev: brain listens here; Vite proxies `/api` → this URL (see ui/vite.config.ts).
API_PORT ?= 8002
export API_PORT
VITE_PROXY_TARGET ?= http://127.0.0.1:$(API_PORT)
export VITE_PROXY_TARGET

# OCI Distribution (``infra/distribution``): host:port for ``docker push`` / ``docker pull`` from this machine.
# Must match ``REGISTRY_PUBLISH_PORT`` on the distribution compose file. Add to Docker ``insecure-registries`` for HTTP.
REGISTRY_PUBLISH_PORT ?= 5000
export REGISTRY_PUBLISH_PORT
DATASYN_IMAGE_REGISTRY ?= localhost:$(REGISTRY_PUBLISH_PORT)
export DATASYN_IMAGE_REGISTRY
DATASYN_IMAGE_NAMESPACE ?= datasyn
export DATASYN_IMAGE_NAMESPACE
DATASYN_IMAGE_TAG ?= latest
export DATASYN_IMAGE_TAG
# Dagster MCP ``build_image`` mirror prefix (same as ``<registry>/<namespace>`` in image refs).
DOCKER_REGISTRY ?= $(DATASYN_IMAGE_REGISTRY)/$(DATASYN_IMAGE_NAMESPACE)
export DOCKER_REGISTRY

ROOT_COMPOSE := docker-compose.yaml
INFRA_OBJECT_STORAGE_COMPOSE := infra/object-storage/docker-compose.yaml
INFRA_DISTRIBUTION_COMPOSE := infra/distribution/docker-compose.yaml
INFRA_DUCKDB_COMPOSE := infra/duckdb/docker-compose.yaml
INFRA_DAGSTER_COMPOSE := infra/dagster/docker-compose.yaml

SHARED_NETWORK := infra-datasynk
SHARED_VOLUMES := duckdb_data storage

.PHONY: help bootstrap bootstrap-infra-primitives registry-up registry-down \
	registry-api-v2 registry-catalog-v2 storage-mcp-manifest-v2 \
	images-prepare images-build images-build-remote images-push images-push-remote images-pull \
	publish publish-remote \
	infra-build infra-up infra-down infra-ps infra-logs \
	infra-duckdb-ui-up infra-duckdb-ui-down \
	dagster-user-code-image dagster-user-code-build-push-remote \
	mcp-build mcp-up mcp-down mcp-ps mcp-logs \
	storage-mcp-buildx-ensure storage-mcp-build-push-remote \
	agent-build agent-up agent-down agent-ps agent-logs \
	agent-dev agent-dev-brain agent-dev-ui \
	stack-up stack-down stack-ps

help:
	@echo "Datacyber — common targets"
	@echo ""
	@echo "  make bootstrap              # network infra-datasynk + volumes duckdb_data, storage"
	@echo "  make registry-up            # OCI Distribution registry (infra/distribution)"
	@echo "  make images-prepare         # registry-up + build all stack images"
	@echo "  make images-build           # build only (tags use Makefile DATASYN_* + DOCKER_REGISTRY)"
	@echo "  make images-push            # push built images to the local registry (needs registry-up)"
	@echo "  make images-pull            # pull stack images from the registry"
	@echo "  make publish                # images-prepare + images-push (CI / golden images)"
	@echo "  make publish-remote         # build + push to external DATASYN_IMAGE_REGISTRY (no local registry-up)"
	@echo "      # Example: make publish-remote DATASYN_IMAGE_REGISTRY=10.13.10.119:5000"
	@echo "  make images-build-remote    # same as images-build + DOCKER_DEFAULT_PLATFORM (external registry only)"
	@echo "  make images-push-remote     # push only (Skopeo; HTTP registries without Engine insecure-registries)"
	@echo "  make infra-up               # bootstrap + registry + object-storage, duckdb, dagster infra"
	@echo "  make infra-down | infra-ps | infra-logs"
	@echo "  make agent-up               # root compose (brain, ui)"
	@echo "  make stack-up               # infra-up then agent-up"
	@echo "  make mcp-up                 # minio + MCPs + duckdb + dagster-mcp (uses same image env vars)"
	@echo "  make registry-api-v2        # GET /v2/ on REGISTRY_HTTP_URL (Distribution spec)"
	@echo "  make storage-mcp-build-push-remote  # buildx linux/amd64 + push storage-mcp (set DATASYN_IMAGE_REGISTRY)"
	@echo "  make dagster-user-code-build-push-remote  # buildx linux/amd64 + push dagster_user_code_image (set DATASYN_IMAGE_REGISTRY)"
	@echo "  make agent-dev              # brain + Vite on host (see compose.env)"
	@echo ""
	@echo "Legacy alias: bootstrap-infra-primitives → bootstrap ; infra-build → images-build"

bootstrap:
	@docker network inspect "$(SHARED_NETWORK)" >/dev/null 2>&1 || docker network create "$(SHARED_NETWORK)"
	@for v in $(SHARED_VOLUMES); do \
		docker volume inspect "$$v" >/dev/null 2>&1 || docker volume create "$$v"; \
	done

bootstrap-infra-primitives: bootstrap

registry-up: bootstrap
	docker compose -f "$(INFRA_DISTRIBUTION_COMPOSE)" up -d

registry-down:
	-docker compose -f "$(INFRA_DISTRIBUTION_COMPOSE)" down

# OCI Distribution HTTP API v2 (https://distribution.github.io/distribution/spec/api/).
# Default targets a remote registry; override if yours is local (e.g. http://127.0.0.1:5000).
REGISTRY_HTTP_URL ?= http://10.13.10.119:5000
DOCKER_PLATFORM_REMOTE ?= linux/amd64

# ``docker compose push`` uses the Engine registry client, which tries HTTPS for non-localhost hosts
# and fails on plain-HTTP registries (``http: server gave HTTP response to HTTPS client``).
# ``images-push-remote`` uses Skopeo in a container (Docker socket + ``--dest-tls-verify=false``)
# so pushes work without editing Docker ``insecure-registries``.
SKOPEO_IMAGE ?= quay.io/skopeo/stable:latest

registry-api-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/"
	@curl -fsS -D- -o /dev/null "$(REGISTRY_HTTP_URL)/v2/" | sed -n '1,20p'

registry-catalog-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/_catalog"
	@curl -fsS "$(REGISTRY_HTTP_URL)/v2/_catalog?n=50"

storage-mcp-manifest-v2:
	@echo "HEAD manifest $(DATASYN_IMAGE_NAMESPACE)/storage-mcp:$(DATASYN_IMAGE_TAG)"
	@curl -fsS -I "$(REGISTRY_HTTP_URL)/v2/$(DATASYN_IMAGE_NAMESPACE)/storage-mcp/manifests/$(DATASYN_IMAGE_TAG)" | sed -n '1,25p'

images-build: bootstrap
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" build
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui build
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" build
	docker compose -f "$(ROOT_COMPOSE)" build

# Build all stack images tagged for an **external** registry (set ``DATASYN_IMAGE_REGISTRY``).
# Sets ``DOCKER_DEFAULT_PLATFORM`` so Apple Silicon (arm64) emits ``linux/amd64`` images servers can pull.
# Example: ``make images-build-remote DATASYN_IMAGE_REGISTRY=10.13.10.119:5000``
images-build-remote: bootstrap
	@if echo "$(DATASYN_IMAGE_REGISTRY)" | grep -Eq '^(localhost|127\.0\.0\.1)(:|$$)'; then \
	  echo "Refusing: set DATASYN_IMAGE_REGISTRY to your external registry host:port (e.g. 10.13.10.119:5000)"; \
	  exit 1; \
	fi
	@cd "$(MAKEFILE_DIR)" && \
	  export DOCKER_DEFAULT_PLATFORM="$(DOCKER_PLATFORM_REMOTE)" && \
	  $(MAKE) images-build

images-prepare: registry-up images-build

images-push: registry-up
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" push
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui push
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" push
	docker compose -f "$(ROOT_COMPOSE)" push brain ui

# Push without ``registry-up`` (for external registries only).
# Uses Skopeo (see ``SKOPEO_IMAGE``) so plain-HTTP registries work without Docker ``insecure-registries``.
images-push-remote:
	@if echo "$(DATASYN_IMAGE_REGISTRY)" | grep -Eq '^(localhost|127\.0\.0\.1)(:|$$)'; then \
	  echo "Refusing: set DATASYN_IMAGE_REGISTRY to your external registry host:port (e.g. 10.13.10.119:5000)"; \
	  exit 1; \
	fi
	@cd "$(MAKEFILE_DIR)" && set -euo pipefail; \
	push_img() { \
	  img="$$1"; \
	  echo "Pushing $$img (skopeo, dest TLS verify off)..."; \
	  dockermount=(); \
	  if [ -d "$${HOME}/.docker" ]; then dockermount=(-v "$${HOME}/.docker:/root/.docker:ro"); fi; \
	  docker run --rm \
	    -v /var/run/docker.sock:/var/run/docker.sock \
	    "$${dockermount[@]}" \
	    "$(SKOPEO_IMAGE)" \
	    copy --dest-tls-verify=false \
	    "docker-daemon:$$img" "docker://$$img"; \
	}; \
	for img in $$(docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" config --images | sort -u); do push_img "$$img"; done; \
	for img in $$(docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui config --images | sort -u); do push_img "$$img"; done; \
	for img in $$(docker compose -f "$(INFRA_DAGSTER_COMPOSE)" config --images | sort -u); do push_img "$$img"; done; \
	for img in $$(docker compose -f "$(ROOT_COMPOSE)" config --images | sort -u); do push_img "$$img"; done

images-pull: registry-up
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" pull
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui pull
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" pull
	docker compose -f "$(ROOT_COMPOSE)" pull

publish: images-prepare images-push

# One-shot: cross-build (default linux/amd64) + push to an external registry.
publish-remote: images-build-remote images-push-remote

dagster-user-code-image:
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" build dagster_user_code

infra-build: images-build

infra-up: bootstrap registry-up
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" up -d
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" up -d
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" up -d

infra-down:
	-docker compose -f "$(INFRA_DAGSTER_COMPOSE)" down
	-docker compose -f "$(INFRA_DUCKDB_COMPOSE)" down
	-docker compose -f "$(INFRA_DISTRIBUTION_COMPOSE)" down
	-docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" down

infra-ps:
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" ps
	docker compose -f "$(INFRA_DISTRIBUTION_COMPOSE)" ps
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" ps
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" ps

infra-logs:
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" logs --tail=100
	docker compose -f "$(INFRA_DISTRIBUTION_COMPOSE)" logs --tail=100
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" logs --tail=100
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" logs --tail=100

infra-duckdb-ui-up: bootstrap
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui up -d --build duckdb-ui

infra-duckdb-ui-down:
	-docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui stop duckdb-ui

mcp-build: bootstrap
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" build storage-mcp
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" build duckdb-mcp
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" build dagster-mcp

mcp-up: bootstrap registry-up
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" up -d minio storage-mcp
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" up -d duckdb duckdb-mcp
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" up -d dagster-mcp

mcp-down:
	-docker compose -f "$(INFRA_DAGSTER_COMPOSE)" stop dagster-mcp
	-docker compose -f "$(INFRA_DUCKDB_COMPOSE)" stop duckdb-mcp
	-docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" stop storage-mcp

mcp-ps:
	@echo "=== object-storage (minio, storage-mcp) ==="
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" ps minio storage-mcp
	@echo "=== duckdb (duckdb, duckdb-mcp) ==="
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" ps duckdb duckdb-mcp
	@echo "=== dagster (dagster-mcp) ==="
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" ps dagster-mcp

mcp-logs:
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" logs --tail=100 storage-mcp
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" logs --tail=100 duckdb-mcp
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" logs --tail=100 dagster-mcp

# Apple Silicon (and other hosts): build ``storage-mcp`` for linux/amd64 and push to REGISTRY.
# Pushes use BuildKit registry config (``infra/distribution/buildkit-registry-insecure.toml``)
# so HTTP registries work without Docker Engine ``insecure-registries`` for buildx.
# First run creates builder ``datasyn-registry-push`` (docker-container driver).
# Example: make storage-mcp-build-push-remote DATASYN_IMAGE_REGISTRY=10.13.10.119:5000
STORAGE_MCP_BUILDX_BUILDER ?= datasyn-registry-push

storage-mcp-buildx-ensure:
	@docker buildx inspect "$(STORAGE_MCP_BUILDX_BUILDER)" >/dev/null 2>&1 || \
	  docker buildx create --name "$(STORAGE_MCP_BUILDX_BUILDER)" --driver docker-container \
	    --config "$(MAKEFILE_DIR)/infra/distribution/buildkit-registry-insecure.toml" --bootstrap

storage-mcp-build-push-remote: storage-mcp-buildx-ensure
	@if echo "$(DATASYN_IMAGE_REGISTRY)" | grep -Eq '^(localhost|127\.0\.0\.1)(:|$$)'; then \
	  echo "Refusing: set DATASYN_IMAGE_REGISTRY to the remote registry host:port (e.g. 10.13.10.119:5000)"; exit 1; \
	fi
	docker buildx build --builder "$(STORAGE_MCP_BUILDX_BUILDER)" --platform "$(DOCKER_PLATFORM_REMOTE)" --provenance=false \
	  -f "$(MAKEFILE_DIR)/infra/object-storage/mcp/Dockerfile" \
	  -t "$(DATASYN_IMAGE_REGISTRY)/$(DATASYN_IMAGE_NAMESPACE)/storage-mcp:$(DATASYN_IMAGE_TAG)" \
	  "$(MAKEFILE_DIR)/infra/object-storage/mcp" --push

# Same buildx builder/config as ``storage-mcp-build-push-remote`` (HTTP registry without Engine insecure-registries).
# Example: make dagster-user-code-build-push-remote DATASYN_IMAGE_REGISTRY=10.13.10.119:5000
dagster-user-code-build-push-remote: storage-mcp-buildx-ensure
	@if echo "$(DATASYN_IMAGE_REGISTRY)" | grep -Eq '^(localhost|127\.0\.0\.1)(:|$$)'; then \
	  echo "Refusing: set DATASYN_IMAGE_REGISTRY to the remote registry host:port (e.g. 10.13.10.119:5000)"; exit 1; \
	fi
	docker buildx build --builder "$(STORAGE_MCP_BUILDX_BUILDER)" --platform "$(DOCKER_PLATFORM_REMOTE)" --provenance=false \
	  -f "$(MAKEFILE_DIR)/infra/dagster/mcp/dagster-code/projects/datasyn/Dockerfile" \
	  -t "$(DATASYN_IMAGE_REGISTRY)/$(DATASYN_IMAGE_NAMESPACE)/dagster_user_code_image:$(DATASYN_IMAGE_TAG)" \
	  "$(MAKEFILE_DIR)/infra/dagster/mcp/dagster-code/projects/datasyn" --push

agent-build: bootstrap
	docker compose -f "$(ROOT_COMPOSE)" build

agent-up: bootstrap registry-up
	docker compose -f "$(ROOT_COMPOSE)" up -d

agent-down:
	docker compose -f "$(ROOT_COMPOSE)" down

agent-ps:
	docker compose -f "$(ROOT_COMPOSE)" ps

agent-logs:
	docker compose -f "$(ROOT_COMPOSE)" logs --tail=100

agent-dev:
	@$(MAKE) -j2 agent-dev-brain agent-dev-ui

agent-dev-brain:
	@echo "[brain] uv run uvicorn … --port $(API_PORT) (sync deps once: uv sync)"
	@echo "       MCP on host: duckdb :8040  storage :8044  dagster :8043 (after mcp-up or infra-up)"
	cd "$(MAKEFILE_DIR)" && uv run uvicorn agent.main:app --host 127.0.0.1 --port $(API_PORT) --reload

agent-dev-ui:
	@echo "[ui] npm run dev → http://127.0.0.1:5173  proxy /api → $(VITE_PROXY_TARGET)"
	cd "$(MAKEFILE_DIR)/ui" && npm run dev

stack-up: infra-up agent-up

stack-down:
	$(MAKE) agent-down
	$(MAKE) mcp-down
	$(MAKE) infra-down

stack-ps: infra-ps mcp-ps agent-ps
