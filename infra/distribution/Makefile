# OCI Distribution registry (prod publish only). Not used when ENVIRONMENT=dev.

DATASYN_ROOT := $(abspath ../..)
SERVICE_COMPOSE := $(DATASYN_ROOT)/infra/distribution/docker-compose.yaml
include $(DATASYN_ROOT)/make/deploy.mk

.PHONY: help up down ps api-v2 catalog-v2

help:
	@echo "infra/distribution — local OCI registry (ENVIRONMENT=prod publish workflow)"
	@echo "  make up | down | ps | api-v2 | catalog-v2"

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
