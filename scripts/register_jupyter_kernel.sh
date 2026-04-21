#!/usr/bin/env bash
# Register a Jupyter kernelspec that uses this repo's .venv Python (ipykernel).
# Run once after: uv sync --extra dev
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "Missing ${VENV_PY}. Run: uv sync --extra dev" >&2
  exit 1
fi
exec "${VENV_PY}" -m ipykernel install --user \
  --name datacyber \
  --display-name "Python (datacyber .venv)"
