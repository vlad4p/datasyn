#!/usr/bin/env bash
# Apply SQL files in catalog/migrations order to an existing database (initdb only runs on first volume).
# Usage: DATABASE_URL=postgresql://user:pass@host:5432/db ./apply_migrations.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="${DATABASE_URL:-}"
if [[ -z "$URL" ]]; then
  echo "Set DATABASE_URL (e.g. postgresql://datacyber:datacyber@127.0.0.1:5432/datacyber_catalog)" >&2
  exit 1
fi
shopt -s nullglob
for f in "$ROOT"/migrations/*.sql; do
  echo "Applying $(basename "$f")..."
  psql "$URL" -v ON_ERROR_STOP=1 -f "$f"
done
echo "Done."
