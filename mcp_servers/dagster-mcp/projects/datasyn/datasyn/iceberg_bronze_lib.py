"""Build Iceberg tables in namespace ``bronze`` from INDEC TXT files via DuckDB Iceberg writes.

Uses DuckDB ≥ 1.4 (ATTACH REST catalog, CREATE TABLE … AS SELECT, INSERT FROM ``read_csv_auto``); see:
https://duckdb.org/2025/11/28/iceberg-writes-in-duckdb

REST catalog attach / secrets:
https://duckdb.org/docs/current/core_extensions/iceberg/iceberg_rest_catalogs.html

Requires ``ICEBERG_REST_ENDPOINT`` and either ``ICEBERG_REST_TOKEN`` (bearer) or OAuth-style
``ICEBERG_REST_CLIENT_ID`` + ``ICEBERG_REST_CLIENT_SECRET`` + ``ICEBERG_REST_OAUTH_URI``.
"""

from __future__ import annotations

import logging
import os
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


def create_iceberg_table_from_txt_paths(
    con: Any,
    *,
    catalog_alias: str,
    iceberg_namespace: str,
    iceberg_table: str,
    paths: list[Path],
) -> dict[str, Any]:
    """Create/replace an Iceberg table by ingesting TXT via ``read_csv_auto`` (semicolon INDEC)."""

    from datasyn.indec_eph_trimestral_lib import read_csv_auto_sql

    if not paths:
        raise FileNotFoundError(f"no TXT files for {iceberg_namespace}.{iceberg_table}")

    ice_fqn = f"{catalog_alias}.{iceberg_namespace}.{iceberg_table}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog_alias}.{iceberg_namespace}")
    con.execute(f"DROP TABLE IF EXISTS {ice_fqn}")
    first = read_csv_auto_sql(paths[0])
    con.execute(f"CREATE TABLE {ice_fqn} AS SELECT * FROM {first} LIMIT 0")
    for p in paths:
        expr = read_csv_auto_sql(p)
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


def materialize_bronze_iceberg_from_txt(
    con: Any,
    *,
    iceberg_namespace: str,
    iceberg_table: str,
    paths: list[Path],
) -> dict[str, Any]:
    """Attach REST catalog (if configured) and load TXT paths into ``namespace.table``."""

    if not iceberg_publish_configured():
        raise ValueError(
            "ICEBERG_REST_ENDPOINT must be set — pipeline is Iceberg-only (no native bronze tables)."
        )

    alias = attach_iceberg_catalog(con)
    if alias is None:
        raise RuntimeError("attach_iceberg_catalog returned None despite ICEBERG_REST_ENDPOINT")

    out = create_iceberg_table_from_txt_paths(
        con,
        catalog_alias=alias,
        iceberg_namespace=iceberg_namespace,
        iceberg_table=iceberg_table,
        paths=paths,
    )
    out["storage"] = "iceberg_rest"
    return out


def materialize_bronze_native_duckdb_from_txt(
    con: Any,
    *,
    schema: str,
    table: str,
    paths: list[Path],
) -> dict[str, Any]:
    """Load TXT into ``schema.table`` in the open DuckDB file (no Iceberg REST catalog)."""

    from datasyn.indec_eph_trimestral_lib import read_csv_auto_sql

    if not paths:
        raise FileNotFoundError(f"no TXT files for {schema}.{table}")

    fqn = f"{schema}.{table}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    con.execute(f"DROP TABLE IF EXISTS {fqn}")
    first = read_csv_auto_sql(paths[0])
    con.execute(f"CREATE TABLE {fqn} AS SELECT * FROM {first} LIMIT 0")
    for p in paths:
        expr = read_csv_auto_sql(p)
        con.execute(f"INSERT INTO {fqn} SELECT * FROM {expr}")

    row = con.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()
    return {
        "ok": True,
        "duckdb_fqn": fqn,
        "row_count": int(row[0]),
        "catalog_alias": None,
        "storage": "duckdb_native",
    }


def materialize_bronze_rows(
    con: Any,
    *,
    iceberg_namespace: str,
    iceberg_table: str,
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
        fqn = f"{alias}.{iceberg_namespace}.{iceberg_table}"
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.{iceberg_namespace}")
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

    fqn = f"{iceberg_namespace}.{iceberg_table}"
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {iceberg_namespace}")
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


def materialize_bronze_from_txt(
    con: Any,
    *,
    iceberg_namespace: str,
    iceberg_table: str,
    paths: list[Path],
) -> dict[str, Any]:
    """Bronze INDEC TXT ingest: Iceberg REST when ``ICEBERG_REST_ENDPOINT`` is set, else native DuckDB."""

    if iceberg_publish_configured():
        return materialize_bronze_iceberg_from_txt(
            con,
            iceberg_namespace=iceberg_namespace,
            iceberg_table=iceberg_table,
            paths=paths,
        )
    return materialize_bronze_native_duckdb_from_txt(
        con,
        schema=iceberg_namespace,
        table=iceberg_table,
        paths=paths,
    )
