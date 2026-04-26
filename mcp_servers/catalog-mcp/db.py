"""PostgreSQL connection helper for catalog-mcp (psycopg 3, dict rows).

``connect()`` is a context manager: it yields a ``psycopg.Connection`` configured
with ``row_factory=dict_row`` so cursors return ``dict`` rows. The connection is
always closed on exit, even if the caller raises.

The database URL comes from ``DATABASE_URL`` (injected by the Compose file). We
validate on first use so the /health endpoint and tool calls surface a clear
error when the env var is missing instead of failing deep inside psycopg.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


log = logging.getLogger("catalog-mcp")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set for catalog-mcp; set it in the Compose file "
            "(e.g. postgresql://datacyber:datacyber@catalog-db:5432/datacyber_catalog)."
        )
    return url


@contextmanager
def connect(*, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Yield a psycopg 3 connection with dict rows, then close it.

    Usage:
        with connect(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                ...
    """

    conn = psycopg.connect(
        _database_url(),
        autocommit=autocommit,
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            log.exception("catalog-mcp: error closing connection")
