"""Object storage MCP (FastMCP HTTP): MinIO/S3 bucket and object operations."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

_env = Path(__file__).resolve().parent / ".env"
if _env.is_file():
    load_dotenv(_env)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [storage-mcp] %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("storage-mcp")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8044"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://datacyber-object-minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin123")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() in {"1", "true", "yes", "on"}
MINIO_DEFAULT_BUCKET = os.environ.get("MINIO_DEFAULT_BUCKET", "data-local")
MAX_TEXT_BYTES = max(1, int(os.environ.get("MAX_TEXT_BYTES", "5242880")))
LIST_PAGE_SIZE = max(1, int(os.environ.get("LIST_PAGE_SIZE", "1000")))

mcp = FastMCP(
    name="storage-mcp",
    instructions=(
        "Datacyber object storage MCP for MinIO/S3. Tools: `list_buckets`, "
        "`list_objects`, `get_object_text`, `put_object_text`, and `delete_object`. "
        "Default bucket is `data-local` unless another bucket is provided."
    ),
)


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        use_ssl=MINIO_SECURE,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _resolve_bucket(bucket: str | None) -> str:
    value = (bucket or "").strip()
    return value or MINIO_DEFAULT_BUCKET


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


@mcp.tool()
def list_buckets() -> str:
    """List available object-storage buckets."""
    log.info("tool list_buckets endpoint=%s", MINIO_ENDPOINT)
    t0 = time.perf_counter()
    try:
        result = _s3().list_buckets()
        buckets = sorted(
            [
                {
                    "name": item.get("Name"),
                    "created_at": item.get("CreationDate"),
                }
                for item in result.get("Buckets", [])
            ],
            key=lambda x: x["name"] or "",
        )
        log.info("tool list_buckets ok count=%s ms=%.2f", len(buckets), (time.perf_counter() - t0) * 1000)
        return _json({"ok": True, "endpoint": MINIO_ENDPOINT, "buckets": buckets})
    except (BotoCoreError, ClientError) as exc:
        log.exception("tool list_buckets failed")
        return _json({"ok": False, "error": _safe_error(exc)})


@mcp.tool()
def list_objects(bucket: str = "", prefix: str = "", max_keys: int = 200) -> str:
    """List objects in a bucket with optional prefix."""
    resolved_bucket = _resolve_bucket(bucket)
    capped_keys = max(1, min(max_keys, LIST_PAGE_SIZE))
    log.info(
        "tool list_objects bucket=%r prefix=%r max_keys=%s",
        resolved_bucket,
        prefix,
        capped_keys,
    )
    t0 = time.perf_counter()
    try:
        result = _s3().list_objects_v2(
            Bucket=resolved_bucket,
            Prefix=prefix or "",
            MaxKeys=capped_keys,
        )
        objects = [
            {
                "key": item.get("Key"),
                "size": item.get("Size"),
                "last_modified": item.get("LastModified"),
                "etag": item.get("ETag"),
            }
            for item in result.get("Contents", [])
        ]
        payload = {
            "ok": True,
            "bucket": resolved_bucket,
            "prefix": prefix or "",
            "is_truncated": bool(result.get("IsTruncated", False)),
            "count": len(objects),
            "objects": objects,
        }
        log.info("tool list_objects ok count=%s ms=%.2f", len(objects), (time.perf_counter() - t0) * 1000)
        return _json(payload)
    except (BotoCoreError, ClientError) as exc:
        log.exception("tool list_objects failed")
        return _json({"ok": False, "bucket": resolved_bucket, "error": _safe_error(exc)})


@mcp.tool()
def get_object_text(bucket: str = "", key: str = "", encoding: str = "utf-8") -> str:
    """Read a text object and return its content."""
    resolved_bucket = _resolve_bucket(bucket)
    object_key = (key or "").strip()
    if not object_key:
        return _json({"ok": False, "error": "ValueError: key is required"})
    log.info("tool get_object_text bucket=%r key=%r", resolved_bucket, object_key)
    t0 = time.perf_counter()
    try:
        result = _s3().get_object(Bucket=resolved_bucket, Key=object_key)
        raw = result["Body"].read(MAX_TEXT_BYTES + 1)
        truncated = len(raw) > MAX_TEXT_BYTES
        if truncated:
            raw = raw[:MAX_TEXT_BYTES]
        text = raw.decode(encoding)
        payload = {
            "ok": True,
            "bucket": resolved_bucket,
            "key": object_key,
            "encoding": encoding,
            "truncated": truncated,
            "text": text,
        }
        log.info("tool get_object_text ok bytes=%s ms=%.2f", len(raw), (time.perf_counter() - t0) * 1000)
        return _json(payload)
    except UnicodeDecodeError as exc:
        log.exception("tool get_object_text decode failed")
        return _json({"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)})
    except (BotoCoreError, ClientError) as exc:
        log.exception("tool get_object_text failed")
        return _json({"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)})


@mcp.tool()
def put_object_text(
    key: str,
    text: str,
    bucket: str = "",
    content_type: str = "text/plain; charset=utf-8",
    create_bucket_if_missing: bool = True,
) -> str:
    """Write text content to an object key."""
    resolved_bucket = _resolve_bucket(bucket)
    object_key = (key or "").strip()
    if not object_key:
        return _json({"ok": False, "error": "ValueError: key is required"})
    log.info("tool put_object_text bucket=%r key=%r bytes=%s", resolved_bucket, object_key, len(text.encode("utf-8")))
    t0 = time.perf_counter()
    client = _s3()
    try:
        if create_bucket_if_missing:
            try:
                client.head_bucket(Bucket=resolved_bucket)
            except ClientError:
                client.create_bucket(Bucket=resolved_bucket)
        body = text.encode("utf-8")
        client.put_object(
            Bucket=resolved_bucket,
            Key=object_key,
            Body=body,
            ContentType=content_type,
        )
        log.info("tool put_object_text ok ms=%.2f", (time.perf_counter() - t0) * 1000)
        return _json(
            {
                "ok": True,
                "bucket": resolved_bucket,
                "key": object_key,
                "bytes_written": len(body),
                "content_type": content_type,
            }
        )
    except (BotoCoreError, ClientError) as exc:
        log.exception("tool put_object_text failed")
        return _json({"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)})


@mcp.tool()
def delete_object(bucket: str = "", key: str = "") -> str:
    """Delete an object from a bucket."""
    resolved_bucket = _resolve_bucket(bucket)
    object_key = (key or "").strip()
    if not object_key:
        return _json({"ok": False, "error": "ValueError: key is required"})
    log.info("tool delete_object bucket=%r key=%r", resolved_bucket, object_key)
    t0 = time.perf_counter()
    try:
        _s3().delete_object(Bucket=resolved_bucket, Key=object_key)
        log.info("tool delete_object ok ms=%.2f", (time.perf_counter() - t0) * 1000)
        return _json({"ok": True, "bucket": resolved_bucket, "key": object_key})
    except (BotoCoreError, ClientError) as exc:
        log.exception("tool delete_object failed")
        return _json({"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)})


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path=MCP_HTTP_PATH,
    )
