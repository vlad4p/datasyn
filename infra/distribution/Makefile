# OCI Distribution registry + prod image publish helpers.

DATASYN_ROOT := $(abspath ../..)
SERVICE_COMPOSE := $(DATASYN_ROOT)/infra/distribution/docker-compose.yaml
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help up down ps api-v2 catalog-v2 \
	images-build images-push images-pull publish publish-remote \
	storage-mcp-build-push-remote storage-mcp-manifest-v2

help:
	@echo "infra/distribution — OCI registry + prod publish (ENVIRONMENT=prod)"
	@echo "  Registry:  make up | down | ps | api-v2 | catalog-v2"
	@echo "  Publish:   make publish ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=<host:port>"
	@echo "             make publish-remote ...   # buildx + skopeo (HTTP registry)"
	@echo "  Storage MCP push: make storage-mcp-build-push-remote ENVIRONMENT=prod ..."

up: registry-up

down: registry-down

ps:
	$(DEPLOY_COMPOSE) -f "$(SERVICE_COMPOSE)" ps

api-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/"
	@curl -fsS -D- -o /dev/null "$(REGISTRY_HTTP_URL)/v2/" | sed -n '1,20p'

catalog-v2:
	@echo "GET $(REGISTRY_HTTP_URL)/v2/_catalog"
	@curl -fsS "$(REGISTRY_HTTP_URL)/v2/_catalog?n=50"

images-build: deploy-images-build
images-push: deploy-images-push
images-pull: deploy-images-pull

publish:
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@$(MAKE) deploy-images-push ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

publish-remote:
	@test "$(ENVIRONMENT)" = "prod" || { echo "Set ENVIRONMENT=prod"; exit 1; }
	@export DOCKER_DEFAULT_PLATFORM="$(DOCKER_PLATFORM_REMOTE)" && \
	  $(MAKE) deploy-images-build ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"
	@$(MAKE) deploy-images-push-skopeo ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY="$(DATASYN_IMAGE_REGISTRY)"

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
