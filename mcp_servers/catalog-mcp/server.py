"""Catalog MCP (FastMCP HTTP): generic PostgreSQL schema + execute_query.

Domain-specific dataset flows live in project ``./skills/catalog-sql``; the brain
composes SQL and calls ``execute_query`` (no direct catalog↔DuckDB link).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from db import connect
from schema_inspect import fetch_public_schema
from sql_guard import validate_catalog_sql

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.is_file():
    load_dotenv(_env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [catalog-mcp] %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("catalog-mcp")

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8041"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")
LIST_CAP = max(1, min(int(os.environ.get("CATALOG_LIST_CAP", "100")), 500))

mcp = FastMCP(
    name="catalog-mcp",
    instructions=(
        "Datacyber metadata catalog (PostgreSQL). Generic tools: **get_schema** (``public`` tables, "
        "columns, foreign keys), **execute_query** (single SELECT / INSERT / UPDATE / DELETE; "
        "no DDL). Dataset list/search/register patterns are documented in the project skill "
        "**`./skills/catalog-sql/SKILL.md`** — the caller builds SQL; this server does not embed "
        "OpenMetadata business APIs."
    ),
)


@mcp.tool()
def get_schema() -> str:
    """Return ``public`` schema as JSON: tables, columns, and foreign keys."""
    t0 = time.perf_counter()
    try:
        with connect(autocommit=True) as conn:
            doc = fetch_public_schema(conn)
        log.info("get_schema ok tables=%s ms=%.2f", len(doc.get("tables") or {}), (time.perf_counter() - t0) * 1000)
        return json.dumps(doc, indent=2, default=str)
    except Exception as exc:
        log.exception("get_schema failed")
        return json.dumps({"error": str(exc), "schema": "public", "tables": {}, "foreign_keys": []}, indent=2)


def _preview(sql: str, max_len: int = 800) -> str:
    s = (sql or "").strip().replace("\n", " ")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


@mcp.tool()
def execute_query(sql: str, max_rows: int = 100) -> str:
    """
    Run one SQL statement against the catalog database.

    * **SELECT** (or ``WITH … SELECT``): returns ``{"rows": [...], "truncated": bool, "max_rows": N}``.
    * **INSERT / UPDATE / DELETE**: returns ``{"ok": true, "rowcount": N}`` (use ``RETURNING`` if you need rows).

    Destructive DDL (``DROP``, ``CREATE TABLE``, ``ALTER``, etc.) is rejected.
    """
    lim = max(1, min(int(max_rows or 100), LIST_CAP))
    err = validate_catalog_sql(sql)
    if err:
        log.warning("execute_query rejected: %s", err)
        return json.dumps({"error": err}, indent=2)

    q = (sql or "").strip()
    log.info("execute_query max_rows=%s preview=%r", lim, _preview(q))
    t0 = time.perf_counter()
    try:
        with connect(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(q)
                if cur.description:
                    rows = cur.fetchmany(lim + 1)
                    truncated = len(rows) > lim
                    rows_out: list[dict[str, Any]] = [dict(r) for r in rows[:lim]]
                    payload = {"rows": rows_out, "truncated": truncated, "max_rows": lim}
                else:
                    payload = {"ok": True, "rowcount": cur.rowcount}
        log.info("execute_query ok ms=%.2f", (time.perf_counter() - t0) * 1000)
        return json.dumps(payload, indent=2, default=str)
    except Exception as exc:
        log.exception("execute_query failed")
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    try:
        with connect(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return PlainTextResponse("ok")
    except Exception as exc:
        return PlainTextResponse(f"error: {exc}", status_code=503)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path=MCP_HTTP_PATH,
    )
