#!/usr/bin/env bash
# Ensure default MinIO bucket exists (fresh MinIO volumes start with no buckets).
# Uses boto3 in python:3.12-slim (minio/mc requires x86-64-v2 on legacy fleet CPUs).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$STACK_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$STACK_DIR/.env"
  set +a
fi

MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin123}"
MINIO_BUCKET="${MINIO_BUCKET:-data-local}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://127.0.0.1:9000}"

if [[ "$MINIO_ENDPOINT" == *datasyn-object-minio* ]]; then
  MINIO_ENDPOINT="http://127.0.0.1:9000"
fi

echo "[object-storage] ensuring bucket s3://${MINIO_BUCKET} at ${MINIO_ENDPOINT}"

docker run --rm --network host python:3.12-slim-bookworm bash -c "
set -euo pipefail
pip install -q boto3
python - <<'PY'
import boto3
endpoint = \"${MINIO_ENDPOINT}\"
bucket = \"${MINIO_BUCKET}\"
user = \"${MINIO_ROOT_USER}\"
password = \"${MINIO_ROOT_PASSWORD}\"
c = boto3.client(
    \"s3\",
    endpoint_url=endpoint,
    aws_access_key_id=user,
    aws_secret_access_key=password,
    region_name=\"us-east-1\",
)
names = [b[\"Name\"] for b in c.list_buckets()[\"Buckets\"]]
print(\"buckets before:\", names)
if bucket not in names:
    c.create_bucket(Bucket=bucket)
    print(\"created:\", bucket)
else:
    print(\"exists:\", bucket)
c.put_object(Bucket=bucket, Key=\"_probe/init-bucket.txt\", Body=b\"ok\")
print(\"probe put_object OK\")
PY
"
