SHELL := /bin/bash

# Repository root (this Makefile lives at the project root).
MAKEFILE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# Local dev: brain listens here; Vite proxies `/api` → this URL (see ui/vite.config.ts).
# Default 8002 matches docker-compose host mapping (brain 8002→8000) and avoids clashes on 8000.
API_PORT ?= 8002
export API_PORT
VITE_PROXY_TARGET ?= http://127.0.0.1:$(API_PORT)
export VITE_PROXY_TARGET

ROOT_COMPOSE := docker-compose.yaml
MCP_COMPOSE := mcp_servers/docker-compose.yaml
INFRA_OBJECT_STORAGE_COMPOSE := infra/object-storage/docker-compose.yaml
INFRA_DUCKDB_COMPOSE := infra/duckdb/docker-compose.yaml
INFRA_DAGSTER_COMPOSE := infra/dagster/docker-compose.yaml
# INFRA_LITELLM_COMPOSE := infra/litellm/docker-compose.yaml
INFRA_TELEGRAM_COMPOSE := infra/telegram_bot/docker-compose.yaml
INFRA_LANGFUSE_COMPOSE := infra/langfuse/docker-compose.yml
DAGSTER_USER_CODE_CONTEXT := mcp_servers/dagster-mcp/projects/datasyn

SHARED_NETWORK := infra-datasynk
SHARED_VOLUMES := duckdb_data storage

.PHONY: help bootstrap-infra-primitives \
	infra-build infra-up infra-down infra-ps infra-logs \
	infra-duckdb-ui-up infra-duckdb-ui-down \
	mcp-build mcp-up mcp-down mcp-ps mcp-logs \
	agent-build agent-up agent-down agent-ps agent-logs \
	agent-dev agent-dev-brain agent-dev-ui \
	stack-up stack-down stack-ps

help:
	@echo "Datacyber orchestration targets"
	@echo ""
	@echo "Bootstrap:"
	@echo "  make bootstrap-infra-primitives  # create shared network + volumes"
	@echo ""
	@echo "Infra:"
	@echo "  make infra-build                 # build infra compose stacks"
	@echo "  make infra-up                    # up infra compose stacks"
	@echo "  make infra-down                  # down infra compose stacks"
	@echo "  make infra-ps                    # ps infra compose stacks"
	@echo "  make infra-logs                  # logs infra compose stacks (tail 100)"
	@echo "  make infra-duckdb-ui-up          # DuckDB Local UI (profile ui; http://127.0.0.1:4213)"
	@echo "  make infra-duckdb-ui-down        # stop DuckDB UI container (releases warehouse lock)"
	@echo ""
	@echo "MCP:"
	@echo "  make mcp-build | mcp-up | mcp-down | mcp-ps | mcp-logs"
	@echo ""
	@echo "Agent/UI:"
	@echo "  make agent-build | agent-up | agent-down | agent-ps | agent-logs"
	@echo "  make agent-dev                   # local: brain (uv) + UI (npm); run make mcp-up first for tools"
	@echo "                                   # API_PORT=$(API_PORT)  MCP→localhost rewrite unless in Docker"
	@echo ""
	@echo "All layers:"
	@echo "  make stack-up                    # infra + mcp + agent"
	@echo "  make stack-down                  # agent + mcp + infra"
	@echo "  make stack-ps                    # infra + mcp + agent"

bootstrap-infra-primitives:
	@docker network inspect "$(SHARED_NETWORK)" >/dev/null 2>&1 || docker network create "$(SHARED_NETWORK)"
	@for v in $(SHARED_VOLUMES); do \
		docker volume inspect "$$v" >/dev/null 2>&1 || docker volume create "$$v"; \
	done

infra-build: bootstrap-infra-primitives
	docker build -t dagster_user_code_image:latest "$(DAGSTER_USER_CODE_CONTEXT)"
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" build
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui build
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" build
	# docker compose -f "$(INFRA_LITELLM_COMPOSE)" build
	docker compose -f "$(INFRA_LANGFUSE_COMPOSE)" build
	docker compose -f "$(INFRA_TELEGRAM_COMPOSE)" build

infra-up: bootstrap-infra-primitives
	docker build -t dagster_user_code_image:latest "$(DAGSTER_USER_CODE_CONTEXT)"
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" up -d
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" up -d
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" up -d
	# docker compose -f "$(INFRA_LITELLM_COMPOSE)" up -d
	docker compose -f "$(INFRA_LANGFUSE_COMPOSE)" up -d
	docker compose -f "$(INFRA_TELEGRAM_COMPOSE)" up -d

infra-down:
	-docker compose -f "$(INFRA_TELEGRAM_COMPOSE)" down
	-docker compose -f "$(INFRA_LANGFUSE_COMPOSE)" down
	# -docker compose -f "$(INFRA_LITELLM_COMPOSE)" down
	-docker compose -f "$(INFRA_DAGSTER_COMPOSE)" down
	-docker compose -f "$(INFRA_DUCKDB_COMPOSE)" down
	-docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" down

infra-ps:
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" ps
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" ps
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" ps
	# docker compose -f "$(INFRA_LITELLM_COMPOSE)" ps
	docker compose -f "$(INFRA_LANGFUSE_COMPOSE)" ps
	docker compose -f "$(INFRA_TELEGRAM_COMPOSE)" ps

infra-logs:
	docker compose -f "$(INFRA_OBJECT_STORAGE_COMPOSE)" logs --tail=100
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" logs --tail=100

infra-duckdb-ui-up: bootstrap-infra-primitives
	docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui up -d --build duckdb-ui

infra-duckdb-ui-down:
	-docker compose -f "$(INFRA_DUCKDB_COMPOSE)" --profile ui stop duckdb-ui
	docker compose -f "$(INFRA_DAGSTER_COMPOSE)" logs --tail=100
	# docker compose -f "$(INFRA_LITELLM_COMPOSE)" logs --tail=100
	docker compose -f "$(INFRA_LANGFUSE_COMPOSE)" logs --tail=100
	docker compose -f "$(INFRA_TELEGRAM_COMPOSE)" logs --tail=100

mcp-build: bootstrap-infra-primitives
	docker compose -f "$(MCP_COMPOSE)" build

mcp-up: bootstrap-infra-primitives
	docker compose -f "$(MCP_COMPOSE)" up -d

mcp-down:
	docker compose -f "$(MCP_COMPOSE)" down

mcp-ps:
	docker compose -f "$(MCP_COMPOSE)" ps

mcp-logs:
	docker compose -f "$(MCP_COMPOSE)" logs --tail=100

agent-build: bootstrap-infra-primitives
	docker compose -f "$(ROOT_COMPOSE)" build

agent-up: bootstrap-infra-primitives
	docker compose -f "$(ROOT_COMPOSE)" up -d

agent-down:
	docker compose -f "$(ROOT_COMPOSE)" down

agent-ps:
	docker compose -f "$(ROOT_COMPOSE)" ps

agent-logs:
	docker compose -f "$(ROOT_COMPOSE)" logs --tail=100

## Local development (host): FastAPI brain + Vite UI — start MCP first so tools resolve (``make mcp-up``).
## Brain maps ``mcp.json`` Docker names → 127.0.0.1:8040 / 8042 / 8043 automatically when not in Docker.
agent-dev:
	@$(MAKE) -j2 agent-dev-brain agent-dev-ui

agent-dev-brain:
	@echo "[brain] uv run uvicorn … --port $(API_PORT) (sync deps once: uv sync)"
	@echo "       MCP on host: duckdb :8040  scrapper :8042  dagster :8043 (after mcp-up)"
	cd "$(MAKEFILE_DIR)" && uv run uvicorn agent.main:app --host 127.0.0.1 --port $(API_PORT) --reload

agent-dev-ui:
	@echo "[ui] npm run dev → http://127.0.0.1:5173  proxy /api → $(VITE_PROXY_TARGET)"
	cd "$(MAKEFILE_DIR)/ui" && npm run dev

stack-up: infra-up mcp-up agent-up

stack-down:
	$(MAKE) agent-down
	$(MAKE) mcp-down
	$(MAKE) infra-down

stack-ps: infra-ps mcp-ps agent-ps
