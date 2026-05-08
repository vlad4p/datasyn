#!/bin/bash
# Run on the EC2 instance (e.g. Session Manager) if cloud-init did not create /opt/litellm.
# Usage:
export LITELLM_CONFIG_BUCKET="mvp-litellm-config-591667019512"
export AWS_REGION="us-east-1"   # optional, defaults to IMDS
#   sudo -E bash scripts/bootstrap-litellm-manual.sh
#
# Bucket name: terraform output -raw config_bucket_id (from your laptop, in live/mvp/litellm/infra).

set -euxo pipefail

if [[ -z "${LITELLM_CONFIG_BUCKET:-}" ]]; then
  echo "export LITELLM_CONFIG_BUCKET=<config_bucket_id from terraform output>" >&2
  exit 1
fi

REGION="${AWS_REGION:-}"
if [[ -z "$REGION" ]]; then
  REGION=$(imds_token=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"); curl -sS -H "X-aws-ec2-metadata-token: $imds_token" http://169.254.169.254/latest/meta-data/placement/region)
fi

mkdir -p /opt/litellm
chmod 755 /opt/litellm
touch /var/log/litellm-bootstrap-manual.log
exec >> /var/log/litellm-bootstrap-manual.log 2>&1
echo "=== manual litellm bootstrap $(date -Is) bucket=$LITELLM_CONFIG_BUCKET region=$REGION ==="

dnf install -y docker awscli
systemctl enable --now docker
usermod -aG docker ec2-user 2>/dev/null || true

if ! dnf install -y docker-compose-plugin 2>/dev/null; then
  COMPOSE_VER="v2.32.4"
  case "$(uname -m)" in
    x86_64) COMPOSE_ARCH=x86_64 ;;
    aarch64) COMPOSE_ARCH=aarch64 ;;
    *) echo "No docker-compose-plugin RPM and no binary fallback for this arch" >&2; exit 1 ;;
  esac
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VER}/docker-compose-linux-${COMPOSE_ARCH}" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

aws s3 cp "s3://$LITELLM_CONFIG_BUCKET/bootstrap/docker-compose.yaml" /opt/litellm/docker-compose.yaml --region "$REGION"
aws s3 cp "s3://$LITELLM_CONFIG_BUCKET/bootstrap/config.yaml" /opt/litellm/config.yaml --region "$REGION"

if [[ ! -f /opt/litellm/.env ]]; then
  cat > /opt/litellm/.env <<'ENVEOF'
LITELLM_MASTER_KEY=sk-mvp-change-me
LITELLM_SALT_KEY=replace-with-long-random-string-use-openssl-rand-hex-32
STORE_MODEL_IN_DB=true
OPENAI_API_KEY=
ENVEOF
  chmod 600 /opt/litellm/.env
fi

cd /opt/litellm
docker compose up -d
echo "=== done $(date -Is) ==="
