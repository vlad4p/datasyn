"""Optional MinIO sync for downloaded files (landing-of-record).

The scraper still writes files under ``DATA_LOCAL_ROOT`` for local compatibility,
then mirrors them to MinIO so the object store is the primary landing zone.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger("scrapper-mcp.minio")


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _settings() -> dict[str, Any]:
    endpoint = (os.environ.get("MINIO_ENDPOINT") or "").strip().rstrip("/")
    bucket = (os.environ.get("MINIO_BUCKET") or "data-local").strip()
    access_key = (os.environ.get("MINIO_ACCESS_KEY") or "").strip()
    secret_key = (os.environ.get("MINIO_SECRET_KEY") or "").strip()
    secure = _as_bool(os.environ.get("MINIO_SECURE"), default=False)
    prefix = (os.environ.get("MINIO_PREFIX") or "").strip().strip("/")
    enabled = _as_bool(os.environ.get("MINIO_SYNC_ENABLED"), default=True)
    return {
        "enabled": enabled,
        "endpoint": endpoint,
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
        "secure": secure,
        "prefix": prefix,
    }


def _build_s3_client(cfg: dict[str, Any]):
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name="us-east-1",
    )


def _ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        if code in (404, 403):
            client.create_bucket(Bucket=bucket)
            return
        raise


def _object_key_for(path: Path, *, root: Path, prefix: str) -> str:
    rel = path.resolve().relative_to(root.resolve()).as_posix().lstrip("/")
    if prefix:
        return f"{prefix}/{rel}"
    return rel


def sync_tree_to_minio(directory: Path, *, root: Path) -> dict[str, Any]:
    """Upload all files in *directory* (recursive) to MinIO.

    Returns a JSON-serializable result; failures are captured in ``errors`` instead
    of raising so the scraper remains usable if object storage is temporarily down.
    """
    cfg = _settings()
    out: dict[str, Any] = {
        "enabled": cfg["enabled"],
        "endpoint": cfg["endpoint"],
        "bucket": cfg["bucket"],
        "prefix": cfg["prefix"],
        "uploaded": 0,
        "errors": [],
    }
    if not cfg["enabled"]:
        out["skipped"] = True
        out["reason"] = "MINIO_SYNC_ENABLED is false"
        return out
    if not cfg["endpoint"] or not cfg["access_key"] or not cfg["secret_key"]:
        out["skipped"] = True
        out["reason"] = "MinIO credentials/env missing"
        return out
    if not directory.exists():
        out["skipped"] = True
        out["reason"] = f"directory does not exist: {directory}"
        return out

    try:
        client = _build_s3_client(cfg)
        _ensure_bucket(client, cfg["bucket"])
    except (BotoCoreError, ClientError, OSError, ValueError) as exc:
        out["errors"].append(f"{type(exc).__name__}: {exc}")
        return out

    for p in sorted(directory.rglob("*")):
        if not p.is_file():
            continue
        key = _object_key_for(p, root=root, prefix=cfg["prefix"])
        try:
            client.upload_file(str(p), cfg["bucket"], key)
            out["uploaded"] += 1
        except (BotoCoreError, ClientError, OSError, ValueError) as exc:
            out["errors"].append(f"{key}: {type(exc).__name__}: {exc}")
    return out

