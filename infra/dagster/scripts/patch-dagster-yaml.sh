#!/usr/bin/env bash
# Render runtime/dagster.local.yaml from dagster.yaml (DockerRunLauncher bind mounts
# do not support env interpolation — substitute DATASYN_DATA_LOCAL_HOST here).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAGSTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATASYN_ROOT="$(cd "$DAGSTER_DIR/../.." && pwd)"
TEMPLATE="$DAGSTER_DIR/runtime/dagster.yaml"
OUTPUT="$DAGSTER_DIR/runtime/dagster.local.yaml"
STACK_ENV="$DAGSTER_DIR/.env"

if [[ -f "$STACK_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$STACK_ENV"
  set +a
fi

HOST_DATA_LOCAL="${DATASYN_DATA_LOCAL_HOST:-$DATASYN_ROOT/data-local}"
HOST_DATA_LOCAL="$(cd "$HOST_DATA_LOCAL" 2>/dev/null && pwd || echo "$HOST_DATA_LOCAL")"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "patch-dagster-yaml: missing template $TEMPLATE" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"
sed "s|__DATASYN_DATA_LOCAL_HOST__|${HOST_DATA_LOCAL}|g" "$TEMPLATE" > "$OUTPUT"
echo "[dagster] runtime config → $OUTPUT (data-local host: $HOST_DATA_LOCAL)"
