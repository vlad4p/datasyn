#!/usr/bin/env bash
# Interactive psql against catalog DB. Set DATABASE_URL or pass connection string as $1.
set -euo pipefail
URL="${1:-${DATABASE_URL:-}}"
if [[ -z "$URL" ]]; then
  echo "Usage: DATABASE_URL=postgresql://... $0 [postgresql://user:pass@host:port/db]" >&2
  exit 1
fi
exec psql "$URL"
