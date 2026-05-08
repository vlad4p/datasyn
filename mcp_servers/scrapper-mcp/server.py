"""Scrapper MCP (FastMCP HTTP): web scrapers for Datacyber sources.

Currently ships one scraper: ``indec_mercado_laboral`` — INDEC Encuesta Permanente
de Hogares (EPH), microdatos en formato TXT. The scraper writes to local
``/data-local/`` (for DuckDB compatibility) and mirrors files to MinIO object
storage when configured (landing-of-record).

Tools (LangChain prefixes them with the MCP key ``scrapper``):

- ``scrapper_list_sources``                      — supported scrapers.
- ``scrapper_indec_mercado_laboral_list``        — HEAD-probe candidates for a period.
- ``scrapper_indec_mercado_laboral_download``    — download + unzip + write metadata.json.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from scrapers import indec_mercado_laboral

_env = Path(__file__).resolve().parent / ".env"
if _env.is_file():
    load_dotenv(_env)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [scrapper-mcp] %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("scrapper-mcp")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8042"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")
DATA_LOCAL_ROOT = Path(os.environ.get("DATA_LOCAL_ROOT", "/data-local")).resolve()
MINIO_ENDPOINT = (os.environ.get("MINIO_ENDPOINT") or "").strip()
MINIO_BUCKET = (os.environ.get("MINIO_BUCKET") or "data-local").strip()

mcp = FastMCP(
    name="scrapper-mcp",
    instructions=(
        "Datacyber scraper MCP: downloads published datasets into /data-local/ so the "
        "warehouse (duckdb-mcp) can read them, and mirrors those files to MinIO object "
        "storage (`MINIO_*` envs) as landing-of-record. Sources: INDEC EPH microdatos (TXT). "
        "Use `list_sources` to see what is supported, `indec_mercado_laboral_list` to "
        "preview candidates (no download), and `indec_mercado_laboral_download` to "
        "persist the ZIPs + extracted TXT + metadata.json. Period input examples: "
        "'Microdatos (2025)', 'Microdatos (2020-2021)', '2016-2019', '2024 Q1,Q3'. "
        "REDATAM and pre-2016 EPH are not supported by this scraper."
    ),
)


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def list_sources() -> str:
    """List the scrapers this MCP exposes (static catalog)."""

    log.info("tool list_sources data_local=%s", DATA_LOCAL_ROOT)
    return _json(
        {
            "data_local_root": str(DATA_LOCAL_ROOT),
            "landing_of_record": {
                "type": "minio" if MINIO_ENDPOINT else "local-only",
                "endpoint": MINIO_ENDPOINT or None,
                "bucket": MINIO_BUCKET if MINIO_ENDPOINT else None,
            },
            "sources": [
                {
                    "key": "indec_mercado_laboral",
                    "title": indec_mercado_laboral.SOURCE_NAME,
                    "page_url": indec_mercado_laboral.PAGE_URL,
                    "supported_years": f">= {indec_mercado_laboral.MIN_SUPPORTED_YEAR}",
                    "period_examples": [
                        "Microdatos (2025)",
                        "Microdatos (2020-2021)",
                        "Microdatos y documentos 2016-2025",
                        "2024 Q1,Q3",
                    ],
                    "output_layout": (
                        "{data_local_root}/indec/mercado_laboral/EPH/{YEAR}/Q{N}/"
                        "EPH_usu_{N}_Trim_{YEAR}_txt.zip + extracted .txt + metadata.json"
                    ),
                    "tools": [
                        "scrapper_indec_mercado_laboral_list",
                        "scrapper_indec_mercado_laboral_download",
                    ],
                }
            ],
        }
    )


@mcp.tool()
def indec_mercado_laboral_list(period: str) -> str:
    """Resolve *period* to candidate EPH datasets and HEAD-probe each URL (no download)."""

    log.info("tool indec_mercado_laboral_list period=%r", period)
    t0 = time.perf_counter()
    try:
        out = indec_mercado_laboral.list_candidates(period)
        log.info(
            "tool indec_mercado_laboral_list ok count=%s ms=%.2f",
            out.get("resolved_count"),
            (time.perf_counter() - t0) * 1000,
        )
        return _json(out)
    except Exception as exc:
        log.exception("indec_mercado_laboral_list failed")
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


@mcp.tool()
def indec_mercado_laboral_download(
    period: str,
    overwrite: bool = False,
    unzip: bool = True,
) -> str:
    """Download each existing candidate for *period* into /data-local/; write metadata.json."""

    log.info(
        "tool indec_mercado_laboral_download period=%r overwrite=%s unzip=%s",
        period,
        overwrite,
        unzip,
    )
    t0 = time.perf_counter()
    try:
        out = indec_mercado_laboral.download(period, overwrite=overwrite, unzip=unzip)
        log.info(
            "tool indec_mercado_laboral_download ok requested=%s succeeded=%s ms=%.2f",
            out.get("requested"),
            out.get("succeeded"),
            (time.perf_counter() - t0) * 1000,
        )
        return _json(out)
    except Exception as exc:
        log.exception("indec_mercado_laboral_download failed")
        return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    DATA_LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path=MCP_HTTP_PATH,
    )
