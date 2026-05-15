"""Shared helpers for landing ZIP downloads, safe unzip, and MinIO tree sync."""

from __future__ import annotations

import hashlib
import logging
import os
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from datasyn.utils.minio_client import boto3_minio_s3_client, resolve_minio_s3_credentials

log = logging.getLogger(__name__)

_CHUNK = 1 << 16

_DEFAULT_PROGRESS_BYTES = int(
    os.environ.get("LANDING_DOWNLOAD_PROGRESS_BYTES", str(10 * 1024 * 1024))
)

EmitFn = Callable[[str], None]


def _emit(emit: EmitFn | None, msg: str) -> None:
    if emit:
        emit(msg)
    else:
        log.info(msg)


def data_local_root() -> Path:
    return Path(os.environ.get("DATA_LOCAL_ROOT", "/data-local")).expanduser().resolve()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def download_zip(
    client: httpx.Client,
    url: str,
    target: Path,
    *,
    overwrite: bool,
    emit: EmitFn | None = None,
    progress_bytes_interval: int | None = None,
) -> dict[str, Any]:
    target = Path(target)
    if target.exists() and not overwrite:
        sz = target.stat().st_size
        _emit(emit, f"[download_zip] cache hit path={target} bytes={sz}")
        return {
            "path": str(target),
            "bytes": sz,
            "sha256": _sha256_file(target),
            "from_cache": True,
        }

    interval = (
        progress_bytes_interval if progress_bytes_interval is not None else _DEFAULT_PROGRESS_BYTES
    )
    t0 = time.perf_counter()
    _emit(emit, f"[download_zip] GET start url={url} -> {target.name}")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.unlink(missing_ok=True)
    sha = hashlib.sha256()
    total = 0
    first = True
    next_log_at = interval
    with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        ct = resp.headers.get("content-type") or ""
        cl = resp.headers.get("content-length")
        _emit(
            emit,
            f"[download_zip] response status={resp.status_code} content_type={ct!r} "
            f"content_length={cl or 'unknown'}",
        )
        if "html" in ct.lower():
            raise RuntimeError(f"refusing HTML body as ZIP ({ct}) url={url}")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(_CHUNK):
                if not chunk:
                    continue
                if first:
                    if not chunk.startswith(b"PK"):
                        tmp.unlink(missing_ok=True)
                        raise RuntimeError(f"response is not a ZIP (no PK magic) url={url}")
                    head = chunk[:6].lstrip()
                    if head.startswith((b"<!DOC", b"<html", b"<HTML")):
                        tmp.unlink(missing_ok=True)
                        raise RuntimeError(f"response looks like HTML url={url}")
                    first = False
                fh.write(chunk)
                sha.update(chunk)
                total += len(chunk)
                if total >= next_log_at:
                    elapsed = time.perf_counter() - t0
                    mb_s = (total / max(elapsed, 1e-6)) / (1024 * 1024)
                    _emit(
                        emit,
                        f"[download_zip] streamed {total / (1024 * 1024):.1f} MiB in {elapsed:.1f}s "
                        f"({mb_s:.2f} MiB/s)",
                    )
                    next_log_at += interval
    os.replace(tmp, target)
    elapsed = time.perf_counter() - t0
    _emit(
        emit,
        f"[download_zip] done bytes={total} sha256={sha.hexdigest()[:12]}… "
        f"elapsed_sec={elapsed:.2f} path={target}",
    )
    return {
        "path": str(target),
        "bytes": total,
        "sha256": sha.hexdigest(),
        "from_cache": False,
        "elapsed_sec": round(elapsed, 3),
    }


def safe_unzip(
    zip_path: Path,
    dest_dir: Path,
    *,
    emit: EmitFn | None = None,
) -> list[str]:
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()
    t0 = time.perf_counter()
    _emit(emit, f"[safe_unzip] open zip={zip_path} dest={dest_dir}")
    extracted: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name or name.endswith("/"):
                continue
            target = (dest_resolved / name).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError:
                log.warning("zip-slip refused: %s -> %s", zip_path, name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                while True:
                    buf = src.read(_CHUNK)
                    if not buf:
                        break
                    dst.write(buf)
            extracted.append(str(target.relative_to(dest_resolved)))
    extracted.sort()
    _emit(
        emit,
        f"[safe_unzip] extracted {len(extracted)} files in {time.perf_counter() - t0:.2f}s",
    )
    return extracted


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def sync_tree_to_minio(
    directory: Path,
    *,
    root: Path,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    endpoint_raw, access_key, secret_key = resolve_minio_s3_credentials()
    endpoint = endpoint_raw.rstrip("/")
    bucket = (os.environ.get("MINIO_BUCKET") or "data-local").strip()
    secure = _as_bool(os.environ.get("MINIO_SECURE"), default=False)
    prefix = (os.environ.get("MINIO_PREFIX") or "").strip().strip("/")
    enabled = _as_bool(os.environ.get("MINIO_SYNC_ENABLED"), default=True)

    out: dict[str, Any] = {
        "enabled": enabled,
        "endpoint": endpoint,
        "bucket": bucket,
        "prefix": prefix,
        "secure": secure,
        "uploaded": 0,
        "errors": [],
    }
    if not enabled:
        out["skipped"] = True
        out["reason"] = "MINIO_SYNC_ENABLED is false"
        _emit(emit, f"[minio] skipped: {out['reason']}")
        return out
    if not endpoint or not access_key or not secret_key:
        out["skipped"] = True
        out["reason"] = "MinIO credentials/env missing"
        _emit(emit, f"[minio] skipped: {out['reason']}")
        return out
    if not directory.exists():
        out["skipped"] = True
        out["reason"] = f"directory missing: {directory}"
        _emit(emit, f"[minio] skipped: {out['reason']}")
        return out

    _emit(
        emit,
        f"[minio] sync start bucket={bucket!r} endpoint={endpoint!r} prefix={prefix!r} dir={directory}",
    )
    t_sync = time.perf_counter()
    try:
        client = boto3_minio_s3_client()
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if code in (404, 403):
                client.create_bucket(Bucket=bucket)
            else:
                raise
    except (BotoCoreError, ClientError, OSError, ValueError) as exc:
        out["errors"].append(f"{type(exc).__name__}: {exc}")
        _emit(emit, f"[minio] client init failed: {exc}")
        return out

    root_res = root.resolve()
    files: list[Path] = []
    for p in sorted(directory.rglob("*")):
        if not p.is_file():
            continue
        files.append(p)
    _emit(emit, f"[minio] uploading {len(files)} files…")
    for p in files:
        rel = p.resolve().relative_to(root_res).as_posix().lstrip("/")
        key = f"{prefix}/{rel}" if prefix else rel
        try:
            client.upload_file(str(p), bucket, key)
            out["uploaded"] += 1
            _emit(emit, f"[minio] uploaded {out['uploaded']}/{len(files)} key={key}")
        except (BotoCoreError, ClientError, OSError, ValueError) as exc:
            out["errors"].append(f"{key}: {type(exc).__name__}: {exc}")
            _emit(emit, f"[minio] ERROR key={key}: {exc}")
    _emit(
        emit,
        f"[minio] done uploaded={out['uploaded']} errors={len(out['errors'])} "
        f"elapsed_sec={time.perf_counter() - t_sync:.2f}",
    )
    return out
