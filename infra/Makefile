# Infra orchestration — Docker stacks under infra/* (shared deploy.mk).
#
#   make bootstrap          # network infra-datasynk + volumes
#   make up                 # object-storage + duckdb + dagster
#   make mcp-up             # minio + MCP servers (if not already up)
#   make stack-up           # infra + brain/ui containers
#
# Per service: make -C infra/<service> help

DATASYN_ROOT := $(abspath ..)
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help bootstrap up down ps logs \
	mcp-up mcp-down mcp-ps mcp-logs \
	stack-up stack-down stack-ps \
	images-build images-build-remote images-push images-push-remote images-pull \
	publish publish-remote \
	dagster-user-code-build dagster-user-code-push

help:
	@echo "infra — Docker stacks  ENVIRONMENT=$(ENVIRONMENT)  prefix=$(DATASYN_IMAGE_PREFIX)"
	@echo ""
	@echo "Orchestration:"
	@echo "  make bootstrap | up | down | ps | logs"
	@echo "  make mcp-up | mcp-down | mcp-ps | mcp-logs"
	@echo "  make stack-up | stack-down | stack-ps   # + brain/ui containers (infra/agent)"
	@echo ""
	@echo "Registry / prod:"
	@echo "  make deploy-print-env"
	@echo "  make publish ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=<host:port>"
	@echo "  make publish-remote ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=<host:port>"
	@echo ""
	@echo "Per stack:"
	@echo "  make -C object-storage help"
	@echo "  make -C duckdb help"
	@echo "  make -C dagster help"
	@echo "  make -C litellm help"
	@echo "  make -C langfuse-deploy help"
	@echo "  make -C distribution help"
	@echo "  make -C agent help"

up: deploy-infra-up

down:
	-$(MAKE) -C dagster down
	-$(MAKE) -C duckdb down
	-$(MAKE) -C distribution down
	-$(MAKE) -C object-storage down

ps:
	@$(MAKE) -C object-storage ps
	-$(MAKE) -C distribution ps
	@$(MAKE) -C duckdb ps
	@$(MAKE) -C dagster ps

logs:
	@$(MAKE) -C object-storage logs
	-$(MAKE) -C distribution logs
	@$(MAKE) -C duckdb logs
	@$(MAKE) -C dagster logs

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

stack-up: up
	@$(MAKE) -C agent up

stack-down:
	@$(MAKE) -C agent down
	@$(MAKE) down

stack-ps: ps mcp-ps
	@$(MAKE) -C agent ps

images-build: deploy-images-build
images-build-remote:
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@export DOCKER_DEFAULT_PLATFORM="$(DOCKER_PLATFORM_REMOTE)" && \
	  $(MAKE) deploy-images-build ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"
images-push: deploy-images-push
images-push-remote: images-build-remote deploy-images-push-skopeo
images-pull: deploy-images-pull

publish:
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@$(MAKE) deploy-images-push ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

publish-remote: images-push-remote

dagster-user-code-build: deploy-dagster-user-code-build

dagster-user-code-push:
	@$(MAKE) -C "$(DATASYN_CODE_DIR)" push ENVIRONMENT=prod \
	  DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"
