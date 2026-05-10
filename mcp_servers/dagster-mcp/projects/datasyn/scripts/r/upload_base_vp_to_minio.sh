#!/usr/bin/env bash
# Upload ./data-local/landing/indec/censo_2022/base_vp.csv to MinIO (landing zone).
# Requires: Docker, network infra-datasynk, bucket data-local, object-storage defaults.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR" && git rev-parse --show-toplevel)"
CSV="${BASE_VP_CSV:-$ROOT/data-local/landing/indec/censo_2022/base_vp.csv}"
ENDPOINT="${MINIO_ENDPOINT:-http://datacyber-object-minio:9000}"
BUCKET="${MINIO_BUCKET:-data-local}"
KEY="${S3_KEY:-landing/indec/censo_2022/base_vp.csv}"

if [[ ! -f "$CSV" ]]; then
  echo "File not found: $CSV" >&2
  echo "Run: Rscript $SCRIPT_DIR/export_base_vp_to_csv.R" >&2
  exit 1
fi

export AWS_ACCESS_KEY_ID="${MINIO_ACCESS_KEY:-minioadmin}"
export AWS_SECRET_ACCESS_KEY="${MINIO_SECRET_KEY:-minioadmin123}"

docker run --rm --network infra-datasynk \
  -v "$CSV:/tmp/base_vp.csv:ro" \
  -e AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY \
  amazon/aws-cli \
  s3 cp /tmp/base_vp.csv "s3://${BUCKET}/${KEY}" \
  --endpoint-url "$ENDPOINT" \
  --region us-east-1

echo "Uploaded to s3://${BUCKET}/${KEY}"
