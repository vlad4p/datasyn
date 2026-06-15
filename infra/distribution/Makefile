# OCI Distribution registry + prod image publish (all stacks).

DATASYN_ROOT := $(abspath ../..)
COMPOSE_FILE := $(DATASYN_ROOT)/infra/distribution/docker-compose.yaml
include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../deploy.mk)

OBJECT_STORAGE_COMPOSE := $(DATASYN_ROOT)/infra/object-storage/docker-compose.yaml
DUCKDB_COMPOSE := $(DATASYN_ROOT)/infra/duckdb/docker-compose.yaml
DAGSTER_COMPOSE := $(DATASYN_ROOT)/infra/dagster/docker-compose.yaml
AGENT_COMPOSE := $(DATASYN_ROOT)/docker-compose.yaml

DATASYN_CODE_DIR ?= $(abspath $(DATASYN_ROOT)/../datasyn-code)
DATASYN_USER_CODE_STUB_DIR := $(abspath $(DATASYN_ROOT)/infra/dagster/user_code)
DATASYN_CODE_BUILD_DIR := $(if $(wildcard $(DATASYN_CODE_DIR)/Dockerfile),$(DATASYN_CODE_DIR),$(DATASYN_USER_CODE_STUB_DIR))
export DATASYN_CODE_DIR := $(DATASYN_CODE_BUILD_DIR)

DOCKER_PLATFORM_REMOTE ?= linux/amd64
# Optional: INCLUDE_DUCKDB_UI=1 to build/push profile ``ui`` (duckdb-ui); omitted from fleet prod by default.
INCLUDE_DUCKDB_UI ?=
DUCKDB_COMPOSE_PROFILES := $(if $(INCLUDE_DUCKDB_UI),--profile ui,)
SKOPEO_IMAGE ?= quay.io/skopeo/stable:latest
STORAGE_MCP_BUILDX_BUILDER ?= datasyn-registry-push
BUILDKIT_CFG := $(DATASYN_ROOT)/infra/distribution/buildkit-registry-insecure.toml

DEPLOY_COMPOSE = DATASYN_IMAGE_PREFIX="$(DATASYN_IMAGE_PREFIX)" DATASYN_IMAGE_TAG="$(DATASYN_IMAGE_TAG)" \
	DATASYN_IMAGE_NAMESPACE="$(DATASYN_IMAGE_NAMESPACE)" DATASYN_CODE_DIR="$(DATASYN_CODE_DIR)" \
	docker compose

.PHONY: help up down ps api-v2 catalog-v2 \
	dagster-user-code-build images-build images-push images-pull \
	publish publish-remote images-push-skopeo \
	agent-build-push-remote agent-manifest-v2 \
	storage-mcp-build-push-remote storage-mcp-manifest-v2

help:
	@echo "infra/distribution — OCI registry + prod publish (ENVIRONMENT=prod)"
	@echo "  Registry:  make bootstrap | up | down | ps | api-v2 | catalog-v2 | print-env"
	@echo "  Publish:   make publish ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=<host:port>"
	@echo "             make publish-remote ...   # buildx + skopeo (HTTP registry)"
	@echo "             INCLUDE_DUCKDB_UI=1 ...   # optional duckdb-ui in publish set"
	@echo "  Storage MCP: make storage-mcp-build-push-remote ENVIRONMENT=prod ..."
	@echo "  Agent only:  make agent-build-push-remote ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=<host:port>"

up: bootstrap
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" up -d

down:
	-$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" down

ps:
	$(DEPLOY_COMPOSE) -f "$(COMPOSE_FILE)" ps

api-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/"
	@curl -fsS -D- -o /dev/null "$(REGISTRY_HTTP_URL)/v2/" | sed -n '1,20p'

catalog-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/_catalog"
	@curl -fsS "$(REGISTRY_HTTP_URL)/v2/_catalog?n=50"

dagster-user-code-build: bootstrap
	$(call deploy_echo_env)
	@if [ "$(DATASYN_CODE_BUILD_DIR)" = "$(DATASYN_USER_CODE_STUB_DIR)" ]; then \
	  docker build -t "$(DATASYN_IMAGE_PREFIX)/dagster_user_code_image:$(DATASYN_IMAGE_TAG)" \
	    -f "$(DATASYN_USER_CODE_STUB_DIR)/Dockerfile" "$(DATASYN_USER_CODE_STUB_DIR)"; \
	else \
	  $(MAKE) -C "$(DATASYN_CODE_DIR)" build ENVIRONMENT="$(ENVIRONMENT)"; \
	fi

images-build: bootstrap dagster-user-code-build
	$(call deploy_echo_env)
	$(DEPLOY_COMPOSE) -f "$(OBJECT_STORAGE_COMPOSE)" build minio storage-mcp
	$(DEPLOY_COMPOSE) -f "$(DUCKDB_COMPOSE)" $(DUCKDB_COMPOSE_PROFILES) build duckdb duckdb-mcp $(if $(INCLUDE_DUCKDB_UI),duckdb-ui,)
	$(DEPLOY_COMPOSE) -f "$(DAGSTER_COMPOSE)" build dagster_postgresql dagster_user_code dagster_webserver
	$(DEPLOY_COMPOSE) -f "$(AGENT_COMPOSE)" build brain ui

images-push: images-build
	$(call deploy_echo_env)
	@test "$(ENVIRONMENT)" = "prod" || { echo "images-push: use ENVIRONMENT=prod"; exit 1; }
	$(DEPLOY_COMPOSE) -f "$(OBJECT_STORAGE_COMPOSE)" push minio storage-mcp
	$(DEPLOY_COMPOSE) -f "$(DUCKDB_COMPOSE)" $(DUCKDB_COMPOSE_PROFILES) push duckdb duckdb-mcp $(if $(INCLUDE_DUCKDB_UI),duckdb-ui,)
	$(DEPLOY_COMPOSE) -f "$(DAGSTER_COMPOSE)" push dagster_postgresql dagster_user_code dagster_webserver dagster_daemon
	$(DEPLOY_COMPOSE) -f "$(AGENT_COMPOSE)" push brain ui

images-pull: bootstrap
	$(call deploy_echo_env)
	@test "$(ENVIRONMENT)" = "prod" || { echo "images-pull: use ENVIRONMENT=prod"; exit 1; }
	$(DEPLOY_COMPOSE) -f "$(OBJECT_STORAGE_COMPOSE)" pull minio storage-mcp
	$(DEPLOY_COMPOSE) -f "$(DUCKDB_COMPOSE)" $(DUCKDB_COMPOSE_PROFILES) pull duckdb duckdb-mcp $(if $(INCLUDE_DUCKDB_UI),duckdb-ui,)
	$(DEPLOY_COMPOSE) -f "$(DAGSTER_COMPOSE)" pull dagster_postgresql dagster_user_code dagster_webserver dagster_daemon
	$(DEPLOY_COMPOSE) -f "$(AGENT_COMPOSE)" pull brain ui

publish:
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@$(MAKE) images-push ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

publish-remote:
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@export DOCKER_BUILDKIT=1 DOCKER_DEFAULT_PLATFORM="$(DOCKER_PLATFORM_REMOTE)" && \
	  $(MAKE) images-build ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"
	@$(MAKE) images-push-skopeo ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

images-push-skopeo:
	@test "$(ENVIRONMENT)" = "prod" || { echo "images-push-skopeo: use ENVIRONMENT=prod"; exit 1; }
	@set -euo pipefail; \
	_prefix="$(DATASYN_IMAGE_PREFIX)"; \
	push_img() { \
	  img="$$1"; echo "Pushing $$img (skopeo)..."; \
	  dockermount=(); [ -d "$${HOME}/.docker" ] && dockermount=(-v "$${HOME}/.docker:/root/.docker:ro"); \
	  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "$${dockermount[@]}" \
	    "$(SKOPEO_IMAGE)" copy --dest-tls-verify=false "docker-daemon:$$img" "docker://$$img"; \
	}; \
	for f in "$(OBJECT_STORAGE_COMPOSE)" "$(DUCKDB_COMPOSE)" "$(DAGSTER_COMPOSE)" "$(AGENT_COMPOSE)"; do \
	  if [ "$$f" = "$(DUCKDB_COMPOSE)" ] && [ -n "$(INCLUDE_DUCKDB_UI)" ]; then \
	    imgs=$$(DATASYN_IMAGE_PREFIX="$$_prefix" docker compose --profile ui -f "$$f" config --images 2>/dev/null | sort -u); \
	  else \
	    imgs=$$(DATASYN_IMAGE_PREFIX="$$_prefix" docker compose -f "$$f" config --images 2>/dev/null | sort -u); \
	  fi; \
	  for img in $$imgs; do \
	    [ -n "$$img" ] && push_img "$$img"; \
	  done; \
	done

storage-mcp-buildx-ensure:
	@docker buildx inspect "$(STORAGE_MCP_BUILDX_BUILDER)" >/dev/null 2>&1 || \
	  docker buildx create --name "$(STORAGE_MCP_BUILDX_BUILDER)" --driver docker-container \
	    --config "$(BUILDKIT_CFG)" --bootstrap

storage-mcp-build-push-remote: storage-mcp-buildx-ensure
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@test -n "$(DATASYN_IMAGE_REGISTRY)" || { echo "Set DATASYN_IMAGE_REGISTRY"; exit 1; }
	@echo "Pushing $(DATASYN_IMAGE_PREFIX)/storage-mcp:$(DATASYN_IMAGE_TAG) ($(DOCKER_PLATFORM_REMOTE))"
	docker buildx build --builder "$(STORAGE_MCP_BUILDX_BUILDER)" --platform "$(DOCKER_PLATFORM_REMOTE)" --provenance=false \
	  -f "$(DATASYN_ROOT)/infra/object-storage/mcp/Dockerfile" \
	  -t "$(DATASYN_IMAGE_PREFIX)/storage-mcp:$(DATASYN_IMAGE_TAG)" \
	  "$(DATASYN_ROOT)/infra/object-storage/mcp" --push

storage-mcp-manifest-v2:
	@echo "HEAD manifest $(DATASYN_IMAGE_NAMESPACE)/storage-mcp:$(DATASYN_IMAGE_TAG)"
	@curl -fsS -I "$(REGISTRY_HTTP_URL)/v2/$(DATASYN_IMAGE_NAMESPACE)/storage-mcp/manifests/$(DATASYN_IMAGE_TAG)" | sed -n '1,25p'

agent-build-push-remote: storage-mcp-buildx-ensure
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@test -n "$(DATASYN_IMAGE_REGISTRY)" || { echo "Set DATASYN_IMAGE_REGISTRY"; exit 1; }
	@echo "Pushing $(DATASYN_IMAGE_PREFIX)/brain:$(DATASYN_IMAGE_TAG) ($(DOCKER_PLATFORM_REMOTE))"
	docker buildx build --builder "$(STORAGE_MCP_BUILDX_BUILDER)" --platform "$(DOCKER_PLATFORM_REMOTE)" --provenance=false \
	  -f "$(DATASYN_ROOT)/Dockerfile" \
	  -t "$(DATASYN_IMAGE_PREFIX)/brain:$(DATASYN_IMAGE_TAG)" \
	  "$(DATASYN_ROOT)" --push
	@echo "Pushing $(DATASYN_IMAGE_PREFIX)/ui:$(DATASYN_IMAGE_TAG) ($(DOCKER_PLATFORM_REMOTE))"
	docker buildx build --builder "$(STORAGE_MCP_BUILDX_BUILDER)" --platform "$(DOCKER_PLATFORM_REMOTE)" --provenance=false \
	  -f "$(DATASYN_ROOT)/ui/Dockerfile" \
	  -t "$(DATASYN_IMAGE_PREFIX)/ui:$(DATASYN_IMAGE_TAG)" \
	  "$(DATASYN_ROOT)/ui" --push

# Fallback when buildx push hits HTTPS-on-HTTP registry (recreate builder or use this target).
agent-build-push-skopeo: bootstrap
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@test -n "$(DATASYN_IMAGE_REGISTRY)" || { echo "Set DATASYN_IMAGE_REGISTRY"; exit 1; }
	$(call deploy_echo_env)
	@export DOCKER_DEFAULT_PLATFORM="$(DOCKER_PLATFORM_REMOTE)" && \
	  $(DEPLOY_COMPOSE) -f "$(AGENT_COMPOSE)" build brain ui
	@set -euo pipefail; \
	_prefix="$(DATASYN_IMAGE_PREFIX)"; \
	_tag="$(DATASYN_IMAGE_TAG)"; \
	push_img() { \
	  img="$$1"; echo "Pushing $$img (skopeo)..."; \
	  dockermount=(); [ -d "$${HOME}/.docker" ] && dockermount=(-v "$${HOME}/.docker:/root/.docker:ro"); \
	  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "$${dockermount[@]}" \
	    "$(SKOPEO_IMAGE)" copy --dest-tls-verify=false "docker-daemon:$$img" "docker://$$img"; \
	}; \
	push_img "$$_prefix/brain:$$_tag"; \
	push_img "$$_prefix/ui:$$_tag"

agent-manifest-v2:
	@echo "HEAD manifest $(DATASYN_IMAGE_NAMESPACE)/brain:$(DATASYN_IMAGE_TAG)"
	@curl -fsS -I "$(REGISTRY_HTTP_URL)/v2/$(DATASYN_IMAGE_NAMESPACE)/brain/manifests/$(DATASYN_IMAGE_TAG)" | sed -n '1,25p'
	@echo "HEAD manifest $(DATASYN_IMAGE_NAMESPACE)/ui:$(DATASYN_IMAGE_TAG)"
	@curl -fsS -I "$(REGISTRY_HTTP_URL)/v2/$(DATASYN_IMAGE_NAMESPACE)/ui/manifests/$(DATASYN_IMAGE_TAG)" | sed -n '1,25p'
