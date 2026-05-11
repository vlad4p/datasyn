"""PostgreSQL connection helper for catalog tools inside dagster-mcp (psycopg 3, dict rows).

``connect()`` is a context manager: it yields a ``psycopg.Connection`` configured
with ``row_factory=dict_row`` so cursors return ``dict`` rows.

URL resolution (first match wins):

* ``DATABASE_URL``
* ``CATALOG_DATABASE_URL``
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("dagster-mcp")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("CATALOG_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL or CATALOG_DATABASE_URL is not set for catalog tools on "
            "dagster-mcp; set one in infra/dagster/.env or the compose environment "
            "(e.g. postgresql://datacyber:datacyber@catalog-db:5432/datacyber_catalog)."
        )
    return url


@contextmanager
def catalog_connect(*, autocommit: bool = False) -> Iterator[psycopg.Connection]:
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
            log.exception("dagster-mcp catalog: error closing connection")
