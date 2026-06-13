#!/usr/bin/env bash
# Expand minimal deploy .env for docker compose / Make.
# Usage: source infra/expand-deploy-env.sh [path/to/.env]
# Required in .env: DATASYN_IMAGE_REGISTRY, LITELLM_MASTER_KEY (see .env.deploy.example).
set -euo pipefail

ENV_FILE="${1:-${DATASYN_ENV_FILE:-}}"
if [[ -z "$ENV_FILE" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  if [[ -f "$REPO_ROOT/.env" ]]; then
    ENV_FILE="$REPO_ROOT/.env"
  fi
fi

if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export DATASYN_IMAGE_NAMESPACE="${DATASYN_IMAGE_NAMESPACE:-datasyn}"
export DATASYN_IMAGE_TAG="${DATASYN_IMAGE_TAG:-latest}"

if [[ -n "${DATASYN_IMAGE_REGISTRY:-}" ]]; then
  export DATASYN_IMAGE_PREFIX="${DATASYN_IMAGE_REGISTRY}/${DATASYN_IMAGE_NAMESPACE}"
else
  export DATASYN_IMAGE_PREFIX="${DATASYN_IMAGE_PREFIX:-datasyn}"
fi

if [[ -n "${LITELLM_MASTER_KEY:-}" ]]; then
  export LITELLM_KEY="${LITELLM_MASTER_KEY}"
fi

export ENVIRONMENT="${ENVIRONMENT:-prod}"
