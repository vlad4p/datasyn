"""MinIO / S3 (boto3) helpers for Dagster assets.

``infra/object-storage`` defines the server with ``MINIO_ROOT_USER`` /
``MINIO_ROOT_PASSWORD``. Client code often used ``MINIO_ACCESS_KEY`` /
``MINIO_SECRET_KEY``. Resolve **either** pair so Dagster matches the running MinIO
without maintaining duplicate secrets (avoids ``SignatureDoesNotMatch`` on GetObject).
"""

from __future__ import annotations

import os
from typing import Any

import boto3


def resolve_minio_s3_credentials() -> tuple[str, str, str]:
    """Return ``(endpoint_url, access_key_id, secret_access_key)`` from the environment."""
    endpoint = (os.environ.get("MINIO_ENDPOINT") or "").strip()
    access_key = (
        (os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER") or "").strip()
    )
    secret_key = (
        (os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD") or "").strip()
    )
    return endpoint, access_key, secret_key


def boto3_minio_s3_client(*, region_name: str = "us-east-1") -> Any:
    """Build a boto3 S3 client pointed at MinIO, or raise ``ValueError`` if config is incomplete."""
    endpoint, access_key, secret_key = resolve_minio_s3_credentials()
    if not endpoint or not access_key or not secret_key:
        raise ValueError(
            "MinIO client requires MINIO_ENDPOINT plus either "
            "(MINIO_ACCESS_KEY and MINIO_SECRET_KEY) or "
            "(MINIO_ROOT_USER and MINIO_ROOT_PASSWORD) matching "
            "infra/object-storage MINIO_ROOT_*."
        )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region_name,
    )
