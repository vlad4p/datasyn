"""INDEC EPH trimestral TXT pipeline helpers.

Landing zone mirrors the public ZIP layout documented by INDEC
(`Encuesta Permanente de Hogares`, microdatos 2016–present): archives are fetched from
``https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/`` as
``EPH_usu_<Q>_Trim_<YEAR>_txt.zip`` (see also the bases-de-datos portal:
https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos).

``read_csv_auto`` helpers (semicolon, European decimals) back Iceberg ingest in ``iceberg_bronze_lib``.

Reading Iceberg with DuckDB: https://duckdb.org/docs/current/core_extensions/iceberg/overview
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger(__name__)

FTP_ROOT = "https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/"
SOURCE_PAGE = "https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos"

BRONZE_SCHEMA = "bronze"
TABLE_HOGAR = "indec_usu_hogar"
TABLE_INDIVIDUAL = "indec_usu_individual"

_CHUNK = 1 << 16

# Log HTTP stream progress every N bytes (env override); reduces UI spam while surfacing stalls.
_DEFAULT_PROGRESS_BYTES = int(
    os.environ.get("INDEC_EPH_DOWNLOAD_PROGRESS_BYTES", str(10 * 1024 * 1024))
)


EmitFn = Callable[[str], None]


def _emit(emit: EmitFn | None, msg: str) -> None:
    if emit:
        emit(msg)
    else:
        log.info(msg)


def data_local_root() -> Path:
    return Path(os.environ.get("DATA_LOCAL_ROOT", "/data-local")).expanduser().resolve()


def quarter_zip_name(year: int, quarter: int) -> str:
    return f"EPH_usu_{quarter}_Trim_{year}_txt.zip"


def quarter_txt_tag(quarter: int, year: int) -> str:
    return f"T{quarter}{year % 100:02d}"


LANDING_SUBDIR = Path("landing/indec/eph")


def quarter_dir(year: int, quarter: int) -> Path:
    return (
        data_local_root()
        / LANDING_SUBDIR
        / str(year)
        / f"Q{quarter}"
    )


def _header(resp: httpx.Response, name: str) -> str | None:
    v = resp.headers.get(name)
    return str(v) if v is not None else None


def head_probe(client: httpx.Client, url: str) -> dict[str, Any]:
    try:
        r = client.head(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {"exists": False, "status": 0, "error": str(exc)}
    ok = r.status_code == 200
    ct = (r.headers.get("content-type") or "").lower()
    detail = ""
    if "html" in ct:
        ok = False
        detail = f"non-asset content-type {ct!r} (likely SPA fallback)"
    elif not ok:
        detail = f"HTTP {r.status_code}"
    return {
        "exists": ok,
        "status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "content_length": int(r.headers.get("content-length") or 0) or None,
        "etag": _header(r, "etag"),
        "last_modified": _header(r, "last-modified"),
        "detail": detail or None,
    }


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

    interval = progress_bytes_interval if progress_bytes_interval is not None else _DEFAULT_PROGRESS_BYTES
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
    endpoint = (os.environ.get("MINIO_ENDPOINT") or "").strip().rstrip("/")
    bucket = (os.environ.get("MINIO_BUCKET") or "data-local").strip()
    access_key = (os.environ.get("MINIO_ACCESS_KEY") or "").strip()
    secret_key = (os.environ.get("MINIO_SECRET_KEY") or "").strip()
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
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )
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


@dataclass(frozen=True)
class QuarterPaths:
    year: int
    quarter: int
    out_dir: Path
    zip_path: Path
    url: str


def quarter_paths(year: int, quarter: int) -> QuarterPaths:
    od = quarter_dir(year, quarter)
    fn = quarter_zip_name(year, quarter)
    return QuarterPaths(
        year=year,
        quarter=quarter,
        out_dir=od,
        zip_path=od / fn,
        url=f"{FTP_ROOT}{fn}",
    )


def write_metadata(qp: QuarterPaths, dl: dict[str, Any], unzipped: list[str]) -> Path:
    meta = {
        "source_page": SOURCE_PAGE,
        "year": qp.year,
        "quarter": qp.quarter,
        "url": qp.url,
        "zip_path": qp.zip_path.as_posix(),
        "sha256": dl.get("sha256"),
        "bytes": dl.get("bytes"),
        "from_cache": dl.get("from_cache"),
        "unzipped_files": unzipped,
        "txt_tag": quarter_txt_tag(qp.quarter, qp.year),
    }
    path = qp.out_dir / "metadata.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def download_year_trimesters(
    *,
    year: int,
    quarters: tuple[int, ...] = (1, 2, 3, 4),
    overwrite: bool = False,
    unzip: bool = True,
    timeout_s: float | None = None,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    """Download each requested quarter ZIP, unzip TXT microdata, mirror to MinIO."""

    if timeout_s is None:
        timeout_s = float(os.environ.get("INDEC_EPH_DOWNLOAD_TIMEOUT_S", "1800"))

    results: list[dict[str, Any]] = []
    ok = 0
    root = data_local_root()
    run_t0 = time.perf_counter()
    _emit(
        emit,
        f"[indec_eph_trimestral] start year={year} quarters={list(quarters)} "
        f"data_local_root={root} httpx_timeout_sec={timeout_s}",
    )
    timeout = httpx.Timeout(timeout_s)
    with httpx.Client(timeout=timeout) as client:
        for q in quarters:
            qp = quarter_paths(year, q)
            q_t0 = time.perf_counter()
            _emit(emit, f"[quarter Q{q}] HEAD {qp.url}")
            probe = head_probe(client, qp.url)
            if not probe.get("exists"):
                _emit(
                    emit,
                    f"[quarter Q{q}] HEAD miss status={probe.get('status')} detail={probe.get('detail')}",
                )
                results.append(
                    {
                        "year": year,
                        "quarter": q,
                        "ok": False,
                        "skipped": True,
                        "reason": probe.get("detail") or f"HEAD failed ({probe.get('status')})",
                        "elapsed_sec": round(time.perf_counter() - q_t0, 3),
                    }
                )
                continue
            _emit(
                emit,
                f"[quarter Q{q}] HEAD ok content_length={probe.get('content_length')} "
                f"out_dir={qp.out_dir}",
            )
            try:
                dl = download_zip(
                    client,
                    qp.url,
                    qp.zip_path,
                    overwrite=overwrite,
                    emit=emit,
                )
                unzipped: list[str] = []
                if unzip:
                    unzipped = safe_unzip(qp.zip_path, qp.out_dir, emit=emit)
                meta_path = write_metadata(qp, dl, unzipped)
                sync_res = sync_tree_to_minio(qp.out_dir, root=root, emit=emit)
                ok += 1
                q_elapsed = time.perf_counter() - q_t0
                _emit(emit, f"[quarter Q{q}] complete ok elapsed_sec={q_elapsed:.2f}")
                results.append(
                    {
                        "year": year,
                        "quarter": q,
                        "ok": True,
                        "zip_path": dl["path"],
                        "metadata_path": str(meta_path),
                        "object_storage": sync_res,
                        "elapsed_sec": round(q_elapsed, 3),
                        "download_elapsed_sec": dl.get("elapsed_sec"),
                    }
                )
            except Exception as exc:
                log.exception("download failed year=%s q=%s", year, q)
                _emit(emit, f"[quarter Q{q}] FAILED {type(exc).__name__}: {exc}")
                results.append(
                    {
                        "year": year,
                        "quarter": q,
                        "ok": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "elapsed_sec": round(time.perf_counter() - q_t0, 3),
                    }
                )

    total_elapsed = time.perf_counter() - run_t0
    _emit(
        emit,
        f"[indec_eph_trimestral] finished succeeded={ok}/{len(quarters)} "
        f"total_elapsed_sec={total_elapsed:.2f}",
    )
    return {
        "source_page": SOURCE_PAGE,
        "ftp_root": FTP_ROOT,
        "year": year,
        "quarters_requested": list(quarters),
        "data_local_root": str(root),
        "httpx_timeout_sec": timeout_s,
        "succeeded": ok,
        "datasets": results,
        "total_elapsed_sec": round(total_elapsed, 3),
    }


def discover_txt_paths(year: int, *, hogar: bool) -> list[Path]:
    pattern = "usu_hogar_*.txt" if hogar else "usu_individual_*.txt"
    root = data_local_root() / LANDING_SUBDIR / str(year)
    if not root.is_dir():
        return []
    paths = sorted(root.glob(f"**/{pattern}"))
    return paths


def read_csv_auto_sql(path: Path) -> str:
    esc = str(path.resolve()).replace("'", "''")
    return (
        f"read_csv_auto('{esc}', delim=';', header=true, quote='\"', "
        "decimal_separator=',', sample_size=-1)"
    )
