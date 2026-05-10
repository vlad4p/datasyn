#!/usr/bin/env bash
# Mirror UCA CSVs into MinIO under landing/indec/censo/uca/ (bucket data-local by default).
#
# Defaults match the bronze assets in datasyn/assets/bronze/uca_csv.py unless UCA_LANDING_PREFIX
# is overridden there / here.
#
# Usage (from repo root or any cwd):
#   UCA_LOCAL_DIR=/path/to/uca ./mcp_servers/dagster-mcp/projects/datasyn/scripts/r/upload_uca_to_minio.sh
#   FORCE=1 ./mcp_servers/dagster-mcp/projects/datasyn/scripts/r/upload_uca_to_minio.sh
#
# Requires: Docker, network infra-datasynk, object-storage defaults (see upload_base_vp_to_minio.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel)"
UCA_LOCAL_DIR="${UCA_LOCAL_DIR:-$ROOT/data-local/uca}"
PREFIX="${UCA_S3_PREFIX:-landing/indec/censo/uca}"
PREFIX="${PREFIX#/}"
PREFIX="${PREFIX%/}"
ENDPOINT="${MINIO_ENDPOINT:-http://datacyber-object-minio:9000}"
BUCKET="${MINIO_BUCKET:-data-local}"
FORCE="${FORCE:-0}"

if [[ ! -d "$UCA_LOCAL_DIR" ]]; then
  echo "Directory not found: $UCA_LOCAL_DIR" >&2
  echo "Set UCA_LOCAL_DIR to the folder that contains the UCA *.csv files." >&2
  exit 1
fi

export AWS_ACCESS_KEY_ID="${MINIO_ACCESS_KEY:-minioadmin}"
export AWS_SECRET_ACCESS_KEY="${MINIO_SECRET_KEY:-minioadmin123}"

shopt -s nullglob
files=("$UCA_LOCAL_DIR"/*.csv)
if [[ ${#files[@]} -eq 0 ]]; then
  echo "No *.csv files under $UCA_LOCAL_DIR" >&2
  exit 1
fi

object_exists() {
  local key="$1"
  docker run --rm --network infra-datasynk \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    amazon/aws-cli \
    s3api head-object --bucket "$BUCKET" --key "$key" \
    --endpoint-url "$ENDPOINT" \
    --region us-east-1 \
    >/dev/null 2>&1
}

for f in "${files[@]}"; do
  base="$(basename "$f")"
  key="${PREFIX}/${base}"
  if [[ "$FORCE" != "1" ]] && object_exists "$key"; then
    echo "exists s3://${BUCKET}/${key}"
    continue
  fi
  echo "upload $f -> s3://${BUCKET}/${key}"
  docker run --rm --network infra-datasynk \
    -v "$f:/tmp/uca_upload.csv:ro" \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    amazon/aws-cli \
    s3 cp "/tmp/uca_upload.csv" "s3://${BUCKET}/${key}" \
    --endpoint-url "$ENDPOINT" \
    --region us-east-1
done

echo "Done. Prefix s3://${BUCKET}/${PREFIX}/"
