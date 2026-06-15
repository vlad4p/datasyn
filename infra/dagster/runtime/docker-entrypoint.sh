#!/usr/bin/env bash
# Render dagster.yaml from the template before webserver/daemon start.
# DockerRunLauncher container_kwargs.volumes do not support env interpolation.
set -euo pipefail

DAGSTER_HOME="${DAGSTER_HOME:-/opt/dagster/dagster_home}"
TEMPLATE="${DAGSTER_CONFIG_TEMPLATE:-$DAGSTER_HOME/dagster.yaml.template}"
OUTPUT="$DAGSTER_HOME/dagster.yaml"

if [[ -f "$TEMPLATE" ]]; then
  HOST_DATA_LOCAL="${DATASYN_DATA_LOCAL_HOST:-}"
  if [[ -z "$HOST_DATA_LOCAL" ]]; then
    echo "docker-entrypoint: DATASYN_DATA_LOCAL_HOST is required (absolute host path to data-local)" >&2
    exit 1
  fi
  HOST_DATA_LOCAL="$(cd "$HOST_DATA_LOCAL" 2>/dev/null && pwd || echo "$HOST_DATA_LOCAL")"
  sed "s|__DATASYN_DATA_LOCAL_HOST__|${HOST_DATA_LOCAL}|g" "$TEMPLATE" > "$OUTPUT"
  if grep -q '__DATASYN_DATA_LOCAL_HOST__' "$OUTPUT"; then
    echo "docker-entrypoint: failed to substitute __DATASYN_DATA_LOCAL_HOST__ in $OUTPUT" >&2
    exit 1
  fi
  echo "[dagster] rendered $OUTPUT (data-local host: $HOST_DATA_LOCAL)"
elif [[ ! -f "$OUTPUT" ]]; then
  echo "docker-entrypoint: missing template $TEMPLATE and output $OUTPUT" >&2
  exit 1
fi

exec "$@"
