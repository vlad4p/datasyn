"""Streamed HTTP downloads with integrity metadata and safe ZIP extraction.

``download_to`` streams into a ``*.part`` temp file, computes ``sha256``, then
atomically renames. ``safe_unzip`` refuses entries that would escape the target
directory (zip-slip guard).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


log = logging.getLogger("scrapper-mcp")

_CHUNK = 1 << 16


@dataclass(frozen=True)
class DownloadResult:
    url: str
    path: str
    bytes: int
    sha256: str
    etag: str | None
    last_modified: str | None
    content_type: str | None
    elapsed_ms: float
    from_cache: bool


def _header(resp: httpx.Response, name: str) -> str | None:
    v = resp.headers.get(name)
    return str(v) if v is not None else None


def _head_ok_for_zip(resp: httpx.Response) -> tuple[bool, str]:
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    ct = (resp.headers.get("content-type") or "").lower()
    if "html" in ct:
        return False, f"non-asset content-type {ct!r} (likely SPA fallback for missing file)"
    return True, ct or "application/octet-stream"


def head_probe(client: httpx.Client, url: str) -> dict[str, Any]:
    """HEAD probe for existence + size; treat ``text/html`` as missing."""

    try:
        r = client.head(url)
    except httpx.HTTPError as exc:
        return {"exists": False, "status": 0, "error": str(exc)}
    ok, detail = _head_ok_for_zip(r)
    return {
        "exists": ok,
        "status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "content_length": int(r.headers.get("content-length") or 0) or None,
        "etag": _header(r, "etag"),
        "last_modified": _header(r, "last-modified"),
        "detail": detail,
    }


def download_to(
    client: httpx.Client,
    url: str,
    target: Path,
    *,
    overwrite: bool = False,
) -> DownloadResult:
    """Stream *url* to *target*, returning integrity metadata.

    Rejects responses that look like HTML (INDEC's SPA shell) so callers don't
    end up with a 36KB ``*.zip`` that is really the homepage.
    """

    target = Path(target)
    if target.exists() and not overwrite:
        size = target.stat().st_size
        sha = _sha256_file(target)
        return DownloadResult(
            url=url,
            path=str(target),
            bytes=size,
            sha256=sha,
            etag=None,
            last_modified=None,
            content_type=None,
            elapsed_ms=0.0,
            from_cache=True,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    t0 = time.perf_counter()
    sha = hashlib.sha256()
    total = 0
    etag: str | None = None
    last_mod: str | None = None
    ct: str | None = None
    expect_zip = target.suffix.lower() == ".zip"
    first_chunk = True
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        ct = resp.headers.get("content-type")
        if ct and "html" in ct.lower():
            raise RuntimeError(
                f"refusing to save HTML as asset ({ct}); url={url} looks like an SPA 404"
            )
        etag = _header(resp, "etag")
        last_mod = _header(resp, "last-modified")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(_CHUNK):
                if not chunk:
                    continue
                if first_chunk:
                    head_bytes = chunk[:4]
                    if expect_zip and not head_bytes.startswith(b"PK"):
                        tmp.unlink(missing_ok=True)
                        raise RuntimeError(
                            "response is not a ZIP (no PK magic); "
                            f"content-type={ct!r} url={url}"
                        )
                    if head_bytes[:5] in (b"<!DOC", b"<html", b"<HTML"):
                        tmp.unlink(missing_ok=True)
                        raise RuntimeError(
                            f"response looks like HTML (SPA fallback); url={url}"
                        )
                    first_chunk = False
                fh.write(chunk)
                sha.update(chunk)
                total += len(chunk)

    os.replace(tmp, target)
    elapsed = (time.perf_counter() - t0) * 1000
    log.info("download ok url=%s bytes=%s ms=%.1f -> %s", url, total, elapsed, target)
    return DownloadResult(
        url=url,
        path=str(target),
        bytes=total,
        sha256=sha.hexdigest(),
        etag=etag,
        last_modified=last_mod,
        content_type=ct,
        elapsed_ms=round(elapsed, 2),
        from_cache=False,
    )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_unzip(zip_path: Path, dest_dir: Path) -> list[str]:
    """Extract *zip_path* into *dest_dir*, rejecting paths that escape the dest.

    Returns a sorted list of extracted file paths (relative to *dest_dir*).
    """

    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()

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
    return extracted
