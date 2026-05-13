"""Shared DuckDB/Iceberg materialization helpers.

Uses DuckDB >= 1.4 for Iceberg REST catalog writes; see:
https://duckdb.org/2025/11/28/iceberg-writes-in-duckdb

REST catalog attach / secrets:
https://duckdb.org/docs/current/core_extensions/iceberg/iceberg_rest_catalogs.html

Requires ``ICEBERG_REST_ENDPOINT`` and either ``ICEBERG_REST_TOKEN`` (bearer) or OAuth-style
``ICEBERG_REST_CLIENT_ID`` + ``ICEBERG_REST_CLIENT_SECRET`` + ``ICEBERG_REST_OAUTH_URI``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def iceberg_publish_configured() -> bool:
    return bool(os.environ.get("ICEBERG_REST_ENDPOINT", "").strip())


def ensure_iceberg_extensions(con: Any) -> None:
    """Load DuckDB Iceberg + httpfs extensions (INSTALL idempotent on recent DuckDB)."""

    con.execute("INSTALL iceberg;")
    con.execute("LOAD iceberg;")
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")


def _detach_if_present(con: Any, alias: str) -> None:
    try:
        con.execute(f"DETACH DATABASE {alias}")
    except Exception:
        log.debug("detach %s skipped", alias, exc_info=True)


def attach_iceberg_catalog(con: Any) -> str | None:
    """Create REST secret, ATTACH Iceberg catalog. Returns alias or ``None`` if disabled."""

    endpoint = os.environ.get("ICEBERG_REST_ENDPOINT", "").strip()
    if not endpoint:
        return None

    alias = os.environ.get("ICEBERG_ATTACH_ALIAS", "iceberg_bronze").strip()
    warehouse = os.environ.get("ICEBERG_REST_WAREHOUSE", "warehouse").strip()
    secret_name = os.environ.get("ICEBERG_REST_SECRET_NAME", "iceberg_rest_secret").strip()

    ensure_iceberg_extensions(con)

    token = os.environ.get("ICEBERG_REST_TOKEN", "").strip()
    if token:
        con.execute(
            f"""
            CREATE OR REPLACE SECRET {secret_name} (
                TYPE ICEBERG,
                TOKEN {_sql_str(token)}
            );
            """
        )
    else:
        cid = os.environ.get("ICEBERG_REST_CLIENT_ID", "").strip()
        csec = os.environ.get("ICEBERG_REST_CLIENT_SECRET", "").strip()
        oauth = os.environ.get("ICEBERG_REST_OAUTH_URI", "").strip()
        if not (cid and csec and oauth):
            raise ValueError(
                "Iceberg REST auth: set ICEBERG_REST_TOKEN or "
                "ICEBERG_REST_CLIENT_ID + ICEBERG_REST_CLIENT_SECRET + ICEBERG_REST_OAUTH_URI"
            )
        con.execute(
            f"""
            CREATE OR REPLACE SECRET {secret_name} (
                TYPE ICEBERG,
                CLIENT_ID {_sql_str(cid)},
                CLIENT_SECRET {_sql_str(csec)},
                OAUTH2_SERVER_URI {_sql_str(oauth)}
            );
            """
        )

    _detach_if_present(con, alias)
    con.execute(
        f"""
        ATTACH {_sql_str(warehouse)} AS {alias} (
            TYPE ICEBERG,
            SECRET {secret_name},
            ENDPOINT {_sql_str(endpoint)}
        );
        """
    )
    return alias


ReadRelationSql = Callable[[Path], str]


def create_iceberg_table_from_paths(
    con: Any,
    *,
    catalog_alias: str,
    namespace: str,
    table: str,
    paths: list[Path],
    read_relation_sql: ReadRelationSql,
) -> dict[str, Any]:
    """Create/replace an Iceberg table from file paths using a caller-provided read relation."""

    if not paths:
        raise FileNotFoundError(f"no files for {namespace}.{table}")

    ice_fqn = f"{catalog_alias}.{namespace}.{table}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog_alias}.{namespace}")
    con.execute(f"DROP TABLE IF EXISTS {ice_fqn}")
    first = read_relation_sql(paths[0])
    con.execute(f"CREATE TABLE {ice_fqn} AS SELECT * FROM {first} LIMIT 0")
    for p in paths:
        expr = read_relation_sql(p)
        con.execute(f"INSERT INTO {ice_fqn} SELECT * FROM {expr}")

    try:
        con.execute(
            f"""
            CALL set_iceberg_table_properties(
                {ice_fqn},
                {{'write.update.mode': 'merge-on-read', 'write.delete.mode': 'merge-on-read'}}
            );
            """
        )
    except Exception as exc:
        log.warning("set_iceberg_table_properties failed for %s: %s", ice_fqn, exc)

    row = con.execute(f"SELECT COUNT(*) FROM {ice_fqn}").fetchone()
    return {
        "ok": True,
        "iceberg_fqn": ice_fqn,
        "row_count": int(row[0]),
        "catalog_alias": catalog_alias,
    }


def materialize_iceberg_from_paths(
    con: Any,
    *,
    namespace: str,
    table: str,
    paths: list[Path],
    read_relation_sql: ReadRelationSql,
) -> dict[str, Any]:
    """Attach the REST catalog and load file paths into ``namespace.table``."""

    if not iceberg_publish_configured():
        raise ValueError(
            "ICEBERG_REST_ENDPOINT must be set for Iceberg catalog materialization."
        )

    alias = attach_iceberg_catalog(con)
    if alias is None:
        raise RuntimeError("attach_iceberg_catalog returned None despite ICEBERG_REST_ENDPOINT")

    out = create_iceberg_table_from_paths(
        con,
        catalog_alias=alias,
        namespace=namespace,
        table=table,
        paths=paths,
        read_relation_sql=read_relation_sql,
    )
    out["storage"] = "iceberg_rest"
    return out


def materialize_native_duckdb_from_paths(
    con: Any,
    *,
    schema: str,
    table: str,
    paths: list[Path],
    read_relation_sql: ReadRelationSql,
) -> dict[str, Any]:
    """Load file paths into ``schema.table`` in the open DuckDB file."""

    if not paths:
        raise FileNotFoundError(f"no files for {schema}.{table}")

    fqn = f"{schema}.{table}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    con.execute(f"DROP TABLE IF EXISTS {fqn}")
    first = read_relation_sql(paths[0])
    con.execute(f"CREATE TABLE {fqn} AS SELECT * FROM {first} LIMIT 0")
    for p in paths:
        expr = read_relation_sql(p)
        con.execute(f"INSERT INTO {fqn} SELECT * FROM {expr}")

    row = con.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()
    return {
        "ok": True,
        "duckdb_fqn": fqn,
        "row_count": int(row[0]),
        "catalog_alias": None,
        "storage": "duckdb_native",
    }


def materialize_rows(
    con: Any,
    *,
    namespace: str,
    table: str,
    schema_sql: str,
    rows: list[tuple],
    insert_placeholders: str,
) -> dict[str, Any]:
    """Replace ``namespace.table`` with explicit row tuples (Iceberg if configured else native).

    ``schema_sql`` is the column list for ``CREATE TABLE`` (e.g. ``campo VARCHAR, tipo VARCHAR, ...``).
    ``insert_placeholders`` is the matching ``VALUES`` placeholder list (e.g. ``?, ?, ?, ?``).
    """

    if iceberg_publish_configured():
        alias = attach_iceberg_catalog(con)
        if alias is None:
            raise RuntimeError("attach_iceberg_catalog returned None despite ICEBERG_REST_ENDPOINT")
        fqn = f"{alias}.{namespace}.{table}"
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.{namespace}")
        con.execute(f"DROP TABLE IF EXISTS {fqn}")
        con.execute(f"CREATE TABLE {fqn} ({schema_sql})")
        if rows:
            con.executemany(f"INSERT INTO {fqn} VALUES ({insert_placeholders})", rows)
        return {
            "ok": True,
            "iceberg_fqn": fqn,
            "row_count": len(rows),
            "catalog_alias": alias,
            "storage": "iceberg_rest",
        }

    fqn = f"{namespace}.{table}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
    con.execute(f"DROP TABLE IF EXISTS {fqn}")
    con.execute(f"CREATE TABLE {fqn} ({schema_sql})")
    if rows:
        con.executemany(f"INSERT INTO {fqn} VALUES ({insert_placeholders})", rows)
    return {
        "ok": True,
        "duckdb_fqn": fqn,
        "row_count": len(rows),
        "catalog_alias": None,
        "storage": "duckdb_native",
    }


def materialize_from_paths(
    con: Any,
    *,
    namespace: str,
    table: str,
    paths: list[Path],
    read_relation_sql: ReadRelationSql,
) -> dict[str, Any]:
    """Materialize files to Iceberg REST when configured, otherwise native DuckDB."""

    if iceberg_publish_configured():
        return materialize_iceberg_from_paths(
            con,
            namespace=namespace,
            table=table,
            paths=paths,
            read_relation_sql=read_relation_sql,
        )
    return materialize_native_duckdb_from_paths(
        con,
        schema=namespace,
        table=table,
        paths=paths,
        read_relation_sql=read_relation_sql,
    )
