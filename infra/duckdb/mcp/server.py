"""DuckDB warehouse MCP (FastMCP HTTP): generic schema + SQL execution + data mount listing."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from duckdb_service import DuckDBWarehouse

_env = Path(__file__).resolve().parent / ".env"
if _env.is_file():
    load_dotenv(_env)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [duckdb-mcp] %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("duckdb-mcp")

DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb")
SQL_ROW_CAP = max(1, int(os.environ.get("SQL_ROW_CAP", "500")))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8040"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")
DATA_LOCAL_ROOT = Path(os.environ.get("DATA_LOCAL_ROOT", "/data-local")).resolve()
QUACK_BIND_URI = (os.environ.get("QUACK_BIND_URI") or "quack:0.0.0.0:9494").strip()
QUACK_TOKEN = (os.environ.get("QUACK_TOKEN") or "").strip()
QUACK_ENABLE = os.environ.get("QUACK_ENABLE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_db = DuckDBWarehouse(DUCKDB_PATH, sql_row_cap=SQL_ROW_CAP, data_local_root=DATA_LOCAL_ROOT)


def _bootstrap_warehouse() -> None:
    _db.open()
    _db.ensure_minio_s3_secret()
    if QUACK_ENABLE:
        token = _db.start_quack_server(
            QUACK_BIND_URI,
            token=QUACK_TOKEN or None,
            allow_other_hostname=True,
        )
        if token and not QUACK_TOKEN:
            log.info(
                "Quack auto-generated token (set QUACK_TOKEN in env for a stable value): %s",
                token,
            )


mcp = FastMCP(
    name="duckdb-mcp",
    instructions=(
        "Datasyn DuckDB warehouse. Generic tools: **get_schema** (tables/views), **execute_query** (any DuckDB SQL: "
        "DDL/DML/SELECT, ingest via read_csv_auto/read_csv/COPY, CREATE TABLE … AS), **list_data_mount** (read-only "
        f"`ls` under {DATA_LOCAL_ROOT}). "
        "There is NO database_ingest_csv or ingest_csv tool. "
        "Prefer **list_data_mount** for folder trees; alternatively **execute_query** with glob(). "
        "Mount name is **data-local** (not data-load). "
        "Use **one SQL statement per execute_query** call (do not batch multiple CREATE/INSERT with semicolons). "
        "Warehouse RW access is owned by this process (Quack :9494). Do not open warehouse.duckdb from another "
        "process while duckdb-mcp runs (including DuckDB Local UI profile)."
    ),
)


@mcp.tool()
def get_schema() -> str:
    """Return tables and views: ``table_schema``, ``table_name``, ``table_type`` (pipe-separated text)."""
    log.info("tool get_schema duckdb_path=%s", DUCKDB_PATH)
    t0 = time.perf_counter()
    out = _db.get_schema()
    log.info("tool get_schema ok ms=%.2f", (time.perf_counter() - t0) * 1000)
    return out


@mcp.tool()
def execute_query(sql: str) -> str:
    """Execute DuckDB SQL (DDL/DML/SELECT). Same capabilities as the former ``warehouse_query`` tool."""
    text = (sql or "").strip()
    preview = text[:500] + ("…" if len(text) > 500 else "")
    log.info("tool execute_query sql_len=%s preview=%r", len(text), preview)
    t0 = time.perf_counter()
    try:
        out = _db.execute_query(text)
        log.info("tool execute_query ok ms=%.2f", (time.perf_counter() - t0) * 1000)
        return out
    except Exception as exc:
        log.exception("tool execute_query failed: %s", exc)
        return f"Error: {type(exc).__name__}: {exc}"


@mcp.tool()
def list_data_mount(
    path: str = "/data-local",
    recursive: bool = False,
    max_depth: int = 3,
) -> str:
    """List files and directories under the host data mount (read-only). Former ``data_local_ls``."""
    log.info(
        "tool list_data_mount path=%r recursive=%s max_depth=%s root=%s",
        path,
        recursive,
        max_depth,
        DATA_LOCAL_ROOT,
    )
    t0 = time.perf_counter()
    out = _db.list_data_mount(path=path, recursive=recursive, max_depth=max_depth)
    log.info("tool list_data_mount ok ms=%.2f", (time.perf_counter() - t0) * 1000)
    return out


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    _bootstrap_warehouse()
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path=MCP_HTTP_PATH,
    )
