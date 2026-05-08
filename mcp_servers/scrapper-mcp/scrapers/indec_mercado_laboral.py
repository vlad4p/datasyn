"""INDEC — Encuesta Permanente de Hogares (EPH), microdatos en formato **TXT**.

Public index (JS-rendered SPA; not scrapeable without a headless browser):
    https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos-1

Direct asset URLs (stable pattern we verified with HEAD):
    https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/EPH_usu_{Q}_Trim_{YEAR}_txt.zip

Scope: **Microdatos (2016 … current year)** in TXT format. Older periods (2003-2015,
REDATAM 2010-2014) use different conventions and live in different paths; this
module refuses them with a clear error rather than fetching a wrong dataset.

Output layout under ``DATA_LOCAL_ROOT`` (local mirror written by this MCP, read by duckdb-mcp).
Each successful download is also mirrored to MinIO object storage when ``MINIO_*``
env vars are configured.

    <root>/indec/mercado_laboral/EPH/<YEAR>/Q<N>/
        EPH_usu_<N>_Trim_<YEAR>_txt.zip        # original archive
        <extracted *.txt files ...>            # unzipped (when unzip=True)
        metadata.json                          # provenance + suggested FQN
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from utils.download import DownloadResult, download_to, head_probe, safe_unzip
from utils.http import build_client
from utils.minio_sync import sync_tree_to_minio
from utils.paths import data_local_root, resolve_under_root
from utils.period import PeriodItem, parse_period


log = logging.getLogger("scrapper-mcp.indec_mercado_laboral")

SOURCE_NAME = "INDEC - EPH - Microdatos (formato TXT)"
PAGE_URL = "https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos-1"
FTP_ROOT = "https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/"
MIN_SUPPORTED_YEAR = 2016


@dataclass(frozen=True)
class Candidate:
    year: int
    quarter: int
    filename: str
    url: str
    output_dir: Path
    zip_path: Path

    def fqn_suggestion(self) -> str:
        return f"indec.mercado_laboral.EPH_usu_{self.quarter}_Trim_{self.year}_txt"


def _build_candidate(root: Path, item: PeriodItem) -> Candidate:
    if item.year < MIN_SUPPORTED_YEAR:
        raise ValueError(
            f"year {item.year} is before {MIN_SUPPORTED_YEAR}: this scraper only "
            "supports the post-2016 EPH Continua TXT pattern. Extend "
            "scrapers/indec_mercado_laboral.py with the older URL pattern if needed."
        )
    filename = f"EPH_usu_{item.quarter}_Trim_{item.year}_txt.zip"
    url = f"{FTP_ROOT}{filename}"
    out_dir = resolve_under_root(
        root,
        "indec",
        "mercado_laboral",
        "EPH",
        str(item.year),
        f"Q{item.quarter}",
    )
    return Candidate(
        year=item.year,
        quarter=item.quarter,
        filename=filename,
        url=url,
        output_dir=out_dir,
        zip_path=out_dir / filename,
    )


def list_candidates(period: str) -> dict[str, Any]:
    """Resolve *period* into candidate datasets and HEAD-probe each URL."""

    items = parse_period(period)
    root = data_local_root()
    results: list[dict[str, Any]] = []
    with build_client() as client:
        for item in items:
            try:
                cand = _build_candidate(root, item)
            except ValueError as exc:
                results.append(
                    {
                        "year": item.year,
                        "quarter": item.quarter,
                        "exists": False,
                        "skipped": True,
                        "reason": str(exc),
                    }
                )
                continue
            probe = head_probe(client, cand.url)
            results.append(
                {
                    "year": cand.year,
                    "quarter": cand.quarter,
                    "filename": cand.filename,
                    "url": cand.url,
                    "output_dir": str(cand.output_dir),
                    "zip_path": str(cand.zip_path),
                    "fqn_suggestion": cand.fqn_suggestion(),
                    **probe,
                }
            )
    return {
        "source": SOURCE_NAME,
        "page_url": PAGE_URL,
        "period": period,
        "resolved_count": len(results),
        "candidates": results,
    }


def _metadata_for(
    cand: Candidate,
    dl: DownloadResult,
    unzipped: list[str],
) -> dict[str, Any]:
    return {
        "source": SOURCE_NAME,
        "page_url": PAGE_URL,
        "ftp_root": FTP_ROOT,
        "dataset_name": cand.filename.removesuffix(".zip"),
        "fully_qualified_name_suggestion": cand.fqn_suggestion(),
        "year": cand.year,
        "quarter": cand.quarter,
        "format": "txt",
        "file": {
            "name": cand.filename,
            "path": dl.path,
            "bytes": dl.bytes,
            "sha256": dl.sha256,
            "etag": dl.etag,
            "last_modified": dl.last_modified,
            "content_type": dl.content_type,
            "from_cache": dl.from_cache,
        },
        "unzipped_files": unzipped,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _download_one(
    client: httpx.Client,
    cand: Candidate,
    *,
    overwrite: bool,
    unzip: bool,
) -> dict[str, Any]:
    probe = head_probe(client, cand.url)
    if not probe.get("exists"):
        return {
            "year": cand.year,
            "quarter": cand.quarter,
            "url": cand.url,
            "ok": False,
            "skipped": True,
            "reason": probe.get("detail") or f"HEAD failed ({probe.get('status')})",
        }

    cand.output_dir.mkdir(parents=True, exist_ok=True)
    dl = download_to(client, cand.url, cand.zip_path, overwrite=overwrite)
    unzipped: list[str] = []
    if unzip:
        try:
            unzipped = safe_unzip(cand.zip_path, cand.output_dir)
        except Exception as exc:
            log.exception("unzip failed: %s", cand.zip_path)
            return {
                "year": cand.year,
                "quarter": cand.quarter,
                "url": cand.url,
                "zip_path": str(cand.zip_path),
                "ok": False,
                "reason": f"unzip failed: {type(exc).__name__}: {exc}",
            }

    meta = _metadata_for(cand, dl, unzipped)
    meta_path = cand.output_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "year": cand.year,
        "quarter": cand.quarter,
        "url": cand.url,
        "ok": True,
        "from_cache": dl.from_cache,
        "zip_path": dl.path,
        "zip_bytes": dl.bytes,
        "sha256": dl.sha256,
        "unzipped_count": len(unzipped),
        "unzipped_files": unzipped,
        "metadata_path": str(meta_path),
        "fqn_suggestion": cand.fqn_suggestion(),
    }


def download(period: str, *, overwrite: bool = False, unzip: bool = True) -> dict[str, Any]:
    """Download every candidate for *period*; skip missing ones with a reason."""

    items = parse_period(period)
    root = data_local_root()
    results: list[dict[str, Any]] = []
    ok_count = 0
    with build_client() as client:
        for item in items:
            try:
                cand = _build_candidate(root, item)
            except ValueError as exc:
                results.append(
                    {
                        "year": item.year,
                        "quarter": item.quarter,
                        "ok": False,
                        "skipped": True,
                        "reason": str(exc),
                    }
                )
                continue
            try:
                res = _download_one(client, cand, overwrite=overwrite, unzip=unzip)
            except Exception as exc:
                log.exception("download failed: %s", cand.url)
                res = {
                    "year": cand.year,
                    "quarter": cand.quarter,
                    "url": cand.url,
                    "ok": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            if res.get("ok"):
                ok_count += 1
                # Landing-of-record is MinIO object storage; keep local mirror for DuckDB ingestion.
                res["object_storage"] = sync_tree_to_minio(cand.output_dir, root=root)
            results.append(res)
    return {
        "source": SOURCE_NAME,
        "page_url": PAGE_URL,
        "period": period,
        "data_local_root": str(root),
        "requested": len(items),
        "succeeded": ok_count,
        "datasets": results,
    }
