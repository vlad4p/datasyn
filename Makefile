# Datasyn root Makefile — deploy via ``make/deploy.mk`` and ``ENVIRONMENT=dev|prod``.
#
#   make infra-up              # ENVIRONMENT=dev (default): local build, no registry
#   make infra-up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=10.0.0.1:5000
#
# Per-stack: ``make -C infra/duckdb up`` (same ENVIRONMENT rules).

SHELL := /bin/bash
MAKEFILE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
DATASYN_ROOT := $(MAKEFILE_DIR)

include $(DATASYN_ROOT)/make/deploy.mk

# --- Local brain / UI (host uv + Vite; not gated by ENVIRONMENT) ---
API_PORT ?= 8002
export API_PORT
VITE_PROXY_TARGET ?= http://127.0.0.1:$(API_PORT)
export VITE_PROXY_TARGET
UV ?= uv

.PHONY: help bootstrap-infra-primitives \
	registry-api-v2 registry-catalog-v2 storage-mcp-manifest-v2 \
	images-build images-build-remote images-push images-push-remote images-pull \
	publish publish-remote \
	infra-build infra-up infra-down infra-ps infra-logs \
	infra-duckdb-ui-up infra-duckdb-ui-down \
	langfuse-up langfuse-down langfuse-ps langfuse-logs \
	mcp-build mcp-up mcp-down mcp-ps mcp-logs \
	storage-mcp-buildx-ensure storage-mcp-build-push-remote \
	uv-sync test-agent brain-restart \
	agent-build agent-up agent-down agent-ps agent-logs \
	agent-brain agent-dev agent-dev-brain agent-dev-ui dev dev-up dev-down ui-install \
	dagster-user-code-build dagster-user-code-push deploy-print-env \
	stack-up stack-down stack-ps

help:
	@echo "Datasyn — ENVIRONMENT=$(ENVIRONMENT)  DATASYN_IMAGE_PREFIX=$(DATASYN_IMAGE_PREFIX)"
	@echo ""
	@echo "Deploy (same targets for dev and prod; set ENVIRONMENT):"
	@echo "  ENVIRONMENT=dev  (default) — local docker build; image prefix datasyn/…"
	@echo "  ENVIRONMENT=prod — pull from registry; prefix \$$DATASYN_IMAGE_REGISTRY/datasyn/…"
	@echo ""
	@echo "Local dev (brain + UI on host — uv + npm, not containers):"
	@echo "  make dev-up               # Docker: infra only (MinIO, DuckDB, Dagster, MCPs)"
	@echo "  make agent-dev            # Host: uv run brain-dev :8002 + npm run dev :5173"
	@echo "  make dev                  # dev-up then agent-dev (recommended workflow)"
	@echo ""
	@echo "Full stack in Docker (brain + UI in containers — prod-like local):"
	@echo "  make stack-up             # infra-up + agent-up (:8002 brain, :8003 ui)"
	@echo "  make agent-up             # brain + ui containers only"
	@echo ""
	@echo "Infra only:"
	@echo "  make infra-up             # object-storage + duckdb + dagster"
	@echo "  make mcp-up               # minio + duckdb-mcp + storage-mcp"
	@echo "  make langfuse-up          # Langfuse UI :3000 (optional tracing)"
	@echo ""
	@echo "Prod registry:"
	@echo "  make publish ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=<host:port>"
	@echo "  make publish-remote       # buildx + skopeo push (external registry)"
	@echo "  make images-pull ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=<host:port>"
	@echo ""
	@echo "Per infra stack:  make -C infra/<service> {build,up,down,ps,logs}"
	@echo "  make -C ../datasyn-code build ENVIRONMENT=dev|prod"
	@echo ""
	@echo "Host tooling:  make uv-sync | make ui-install | make test-agent | make brain-restart"

bootstrap-infra-primitives: bootstrap

# --- Image lifecycle (aliases → deploy.mk) ---
images-build: deploy-images-build
infra-build: deploy-images-build
dagster-user-code-build: deploy-dagster-user-code-build

dagster-user-code-push:
	@$(MAKE) -C "$(DATASYN_CODE_DIR)" push ENVIRONMENT=prod \
	  DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

images-build-remote:
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@cd "$(DATASYN_ROOT)" && export DOCKER_DEFAULT_PLATFORM="$(DOCKER_PLATFORM_REMOTE)" && \
	  $(MAKE) deploy-images-build ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

images-prepare: registry-up
	@$(MAKE) deploy-images-build ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

images-push: deploy-images-push
images-push-remote: deploy-images-build-remote deploy-images-push-skopeo
images-pull: deploy-images-pull
publish:
	@$(MAKE) deploy-images-push ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"
publish-remote:
	@$(MAKE) images-build-remote ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"
	@$(MAKE) deploy-images-push-skopeo ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

registry-api-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/"
	@curl -fsS -D- -o /dev/null "$(REGISTRY_HTTP_URL)/v2/" | sed -n '1,20p'

registry-catalog-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/_catalog"
	@curl -fsS "$(REGISTRY_HTTP_URL)/v2/_catalog?n=50"

storage-mcp-manifest-v2:
	@echo "HEAD manifest $(DATASYN_IMAGE_NAMESPACE)/storage-mcp:$(DATASYN_IMAGE_TAG)"
	@curl -fsS -I "$(REGISTRY_HTTP_URL)/v2/$(DATASYN_IMAGE_NAMESPACE)/storage-mcp/manifests/$(DATASYN_IMAGE_TAG)" | sed -n '1,25p'

# --- Infra / agent / stack ---
infra-up: deploy-infra-up
infra-down:
	-$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" down
	-$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" down
	-$(DEPLOY_COMPOSE) -f "$(INFRA_DISTRIBUTION_COMPOSE)" down
	-$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" down

infra-ps:
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" ps
	-$(DEPLOY_COMPOSE) -f "$(INFRA_DISTRIBUTION_COMPOSE)" ps
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" ps
	$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" ps

infra-logs:
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" logs --tail=100
	-$(DEPLOY_COMPOSE) -f "$(INFRA_DISTRIBUTION_COMPOSE)" logs --tail=100
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" logs --tail=100
	$(DEPLOY_COMPOSE) -f "$(INFRA_DAGSTER_COMPOSE)" logs --tail=100

infra-duckdb-ui-up:
	@$(MAKE) -C "$(DATASYN_ROOT)/infra/duckdb" ui-up ENVIRONMENT="$(ENVIRONMENT)"

infra-duckdb-ui-down:
	@$(MAKE) -C "$(DATASYN_ROOT)/infra/duckdb" ui-down ENVIRONMENT="$(ENVIRONMENT)"

langfuse-up:
	@$(MAKE) -C "$(DATASYN_ROOT)/infra/langfuse" up

langfuse-down:
	@$(MAKE) -C "$(DATASYN_ROOT)/infra/langfuse" down

langfuse-ps:
	@$(MAKE) -C "$(DATASYN_ROOT)/infra/langfuse" ps

langfuse-logs:
	@$(MAKE) -C "$(DATASYN_ROOT)/infra/langfuse" logs

mcp-build: bootstrap
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" build storage-mcp
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" build duckdb-mcp

mcp-up: deploy-mcp-up
mcp-down:
	-$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" stop duckdb-mcp
	-$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" stop storage-mcp

mcp-ps:
	@echo "=== object-storage ==="
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" ps minio storage-mcp
	@echo "=== duckdb ==="
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" ps duckdb duckdb-mcp

mcp-logs:
	$(DEPLOY_COMPOSE) -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" logs --tail=100 storage-mcp
	$(DEPLOY_COMPOSE) -f "$(INFRA_DUCKDB_COMPOSE)" logs --tail=100 duckdb-mcp

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

agent-build: bootstrap
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" build

agent-up: deploy-agent-up
agent-down:
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" down
agent-ps:
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" ps
agent-logs:
	$(DEPLOY_COMPOSE) -f "$(ROOT_COMPOSE)" logs --tail=100

stack-up: infra-up agent-up
stack-down: agent-down mcp-down infra-down
stack-ps: infra-ps mcp-ps agent-ps

# --- Local dev: infra in Docker, brain (uv) + UI (npm) on host ---
dev-up: bootstrap infra-up
	@echo ""
	@echo "[dev] Infra is up in Docker (ENVIRONMENT=$(ENVIRONMENT))."
	@echo "      Brain and UI run on the host — not in containers."
	@echo ""
	@echo "  cp .env.example .env   # once: LLM keys, MCP"
	@echo "  make uv-sync           # once: Python deps (uv)"
	@echo "  make ui-install        # once: npm deps in ui/"
	@echo "  make agent-dev         # uv brain :$(API_PORT) + Vite :5173"
	@echo ""
	@echo "  UI  → http://127.0.0.1:5173   (proxies /api → brain)"
	@echo "  API → http://127.0.0.1:$(API_PORT)"

dev: dev-up agent-dev

dev-down: infra-down
	@echo "[dev] Infra stopped. Kill brain/vite manually if still running (Ctrl+C or make brain-restart)."

# --- Host Python / UI (uv + npm on host; never use agent-up for daily dev) ---
uv-check:
	@command -v $(UV) >/dev/null 2>&1 || { \
	  echo "uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }

uv-sync: uv-check
	cd "$(DATASYN_ROOT)" && $(UV) sync

ui-install:
	@command -v npm >/dev/null 2>&1 || { echo "npm not found. Install Node.js."; exit 1; }
	cd "$(DATASYN_ROOT)/ui" && npm install

test-agent: uv-sync
	cd "$(DATASYN_ROOT)" && $(UV) run pytest tests/ -q

brain-restart: uv-check
	@echo "[brain] stopping listeners on :$(API_PORT) (if any)…"
	-@lsof -ti tcp:$(API_PORT) | xargs kill 2>/dev/null || true
	@sleep 1
	@$(MAKE) agent-brain

agent-brain: uv-sync
	@echo "[brain] uv run brain-dev → http://127.0.0.1:$(API_PORT)"
	cd "$(DATASYN_ROOT)" && $(UV) run brain-dev

agent-dev:
	@$(MAKE) -j2 agent-dev-brain agent-dev-ui

agent-dev-brain: uv-sync
	@echo "[brain] uv run brain-dev → http://127.0.0.1:$(API_PORT)"
	cd "$(DATASYN_ROOT)" && $(UV) run brain-dev

agent-dev-ui:
	@echo "[ui] npm run dev → http://127.0.0.1:5173  proxy /api → $(VITE_PROXY_TARGET)"
	cd "$(DATASYN_ROOT)/ui" && npm run dev
