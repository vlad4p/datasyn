"""Object storage MCP (FastMCP HTTP): MinIO/S3 bucket and object operations."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
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
# Absolute path prefix for ``put_object_from_path`` (host bind-mount in compose).
STORAGE_MCP_READ_ROOT = os.environ.get("STORAGE_MCP_READ_ROOT", "/data-local")
# Max decoded size for ``put_object_base64`` (PDFs, images, etc. sent over MCP as base64).
MAX_PUT_B64_DECODED_BYTES = max(1, int(os.environ.get("STORAGE_MCP_MAX_PUT_B64_BYTES", str(50 * 1024 * 1024))))

mcp = FastMCP(
    name="storage-mcp",
    instructions=(
        "Datacyber object storage MCP for MinIO/S3. Tools: `list_buckets`, "
        "`list_objects`, `get_object_text`, `put_object_text`, `put_object_base64`, "
        "`put_object_from_path`, and `delete_object`. Default bucket is `data-local` "
        "unless another bucket is provided. Use `put_object_base64` for binary uploads "
        "(PDF, images) from the client; use `put_object_from_path` for large files on the "
        "server mount under STORAGE_MCP_READ_ROOT."
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


def _resolve_under_read_root(source_path: str) -> Path:
    """Return a resolved file path that must live under ``STORAGE_MCP_READ_ROOT``."""
    raw = (source_path or "").strip()
    if not raw:
        raise ValueError("source_path is required")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = Path(STORAGE_MCP_READ_ROOT) / candidate
    resolved = candidate.resolve()
    root = Path(STORAGE_MCP_READ_ROOT).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"path {resolved} escapes allowed root {root} (STORAGE_MCP_READ_ROOT)"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"not a file or missing: {resolved}")
    return resolved


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
    """Write UTF-8 text only. Not for arbitrary binary (PDF/images): bytes are not round-tripped
    through a Unicode string. Use ``put_object_base64`` (client sends base64) or
    ``put_object_from_path`` (file already on the MCP host under ``STORAGE_MCP_READ_ROOT``).
    """
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
def put_object_base64(
    key: str,
    data_base64: str,
    bucket: str = "",
    content_type: str = "",
    create_bucket_if_missing: bool = True,
) -> str:
    """Write binary content to an object key (standard base64; PDF, images, etc.).

    Decoded payload must not exceed ``STORAGE_MCP_MAX_PUT_B64_BYTES`` (default 50 MiB).
    For larger objects, use ``put_object_from_path`` when the file is on the MCP host.
    """
    resolved_bucket = _resolve_bucket(bucket)
    object_key = (key or "").strip()
    if not object_key:
        return _json({"ok": False, "error": "ValueError: key is required"})
    raw_b64 = (data_base64 or "").strip()
    if not raw_b64:
        return _json({"ok": False, "error": "ValueError: data_base64 is required"})
    t0 = time.perf_counter()
    client = _s3()
    try:
        body = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        return _json({"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)})
    if len(body) > MAX_PUT_B64_DECODED_BYTES:
        return _json(
            {
                "ok": False,
                "bucket": resolved_bucket,
                "key": object_key,
                "error": (
                    f"ValueError: decoded size {len(body)} exceeds limit "
                    f"{MAX_PUT_B64_DECODED_BYTES} (set STORAGE_MCP_MAX_PUT_B64_BYTES or use "
                    "put_object_from_path)"
                ),
            }
        )
    ct = (content_type or "").strip()
    if not ct:
        guessed, _ = mimetypes.guess_type(object_key)
        ct = guessed or "application/octet-stream"
    log.info(
        "tool put_object_base64 bucket=%r key=%r bytes=%s",
        resolved_bucket,
        object_key,
        len(body),
    )
    try:
        if create_bucket_if_missing:
            try:
                client.head_bucket(Bucket=resolved_bucket)
            except ClientError:
                client.create_bucket(Bucket=resolved_bucket)
        client.put_object(
            Bucket=resolved_bucket,
            Key=object_key,
            Body=body,
            ContentType=ct,
        )
        log.info("tool put_object_base64 ok ms=%.2f", (time.perf_counter() - t0) * 1000)
        return _json(
            {
                "ok": True,
                "bucket": resolved_bucket,
                "key": object_key,
                "bytes_written": len(body),
                "content_type": ct,
            }
        )
    except (BotoCoreError, ClientError) as exc:
        log.exception("tool put_object_base64 failed")
        return _json({"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)})


@mcp.tool()
def put_object_from_path(
    source_path: str,
    key: str,
    bucket: str = "",
    content_type: str = "",
    create_bucket_if_missing: bool = True,
) -> str:
    """Upload a file from disk (under ``STORAGE_MCP_READ_ROOT``) to an object key.

    Uses boto3 ``upload_file`` so large objects use multipart uploads. Intended for
    bind-mounting the repo ``data-local`` tree at ``/data-local`` in ``storage-mcp``.
    """
    resolved_bucket = _resolve_bucket(bucket)
    object_key = (key or "").strip()
    if not object_key:
        return _json({"ok": False, "error": "ValueError: key is required"})
    log.info(
        "tool put_object_from_path bucket=%r key=%r source=%r",
        resolved_bucket,
        object_key,
        source_path,
    )
    t0 = time.perf_counter()
    client = _s3()
    try:
        src = _resolve_under_read_root(source_path)
        ct = (content_type or "").strip()
        if not ct:
            guessed, _ = mimetypes.guess_type(src.name)
            ct = guessed or "application/octet-stream"
        if create_bucket_if_missing:
            try:
                client.head_bucket(Bucket=resolved_bucket)
            except ClientError:
                client.create_bucket(Bucket=resolved_bucket)
        extra = {"ContentType": ct} if ct else {}
        client.upload_file(str(src), resolved_bucket, object_key, ExtraArgs=extra)
        size = src.stat().st_size
        log.info(
            "tool put_object_from_path ok bytes=%s ms=%.2f",
            size,
            (time.perf_counter() - t0) * 1000,
        )
        return _json(
            {
                "ok": True,
                "bucket": resolved_bucket,
                "key": object_key,
                "source_path": str(src),
                "bytes_written": size,
                "content_type": ct,
            }
        )
    except (OSError, ValueError) as exc:
        log.exception("tool put_object_from_path validation failed")
        return _json(
            {"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)}
        )
    except (BotoCoreError, ClientError) as exc:
        log.exception("tool put_object_from_path failed")
        return _json(
            {"ok": False, "bucket": resolved_bucket, "key": object_key, "error": _safe_error(exc)}
        )


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
