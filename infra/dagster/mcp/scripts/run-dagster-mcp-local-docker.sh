#!/usr/bin/env bash
# Run dagster-mcp locally for Cursor (HTTP on http://127.0.0.1:8043/mcp).
# Prereq: docker network infra-datasynk exists (see repo root ``make bootstrap-infra-primitives``).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
MCP_DIR="${REPO_ROOT}/infra/dagster/mcp"
INFRA_DAGSTER="${REPO_ROOT}/infra/dagster"
IMAGE="${DAGSTER_MCP_LOCAL_IMAGE:-datasyn-dagster-mcp:local}"

docker build -t "${IMAGE}" "${MCP_DIR}"

exec docker run --rm --name "${DAGSTER_MCP_LOCAL_CONTAINER:-datasyn-dagster-mcp-local}" \
  -p 127.0.0.1:8043:8043 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "${MCP_DIR}/dagster-code/projects:/projects" \
  -v "${INFRA_DAGSTER}:/dagster-compose:ro" \
  -e HOST=0.0.0.0 \
  -e PORT=8043 \
  -e MCP_HTTP_PATH=/mcp \
  -e DAGSTER_PROJECTS_ROOT=/projects \
  -e DAGSTER_COMPOSE_FILE=/dagster-compose/docker-compose.yaml \
  -e DAGSTER_COMPOSE_PROJECT="${DAGSTER_COMPOSE_PROJECT:-dagster}" \
  -e DAGSTER_PROJECT_NETWORK=infra-datasynk \
  --network infra-datasynk \
  "${IMAGE}"
