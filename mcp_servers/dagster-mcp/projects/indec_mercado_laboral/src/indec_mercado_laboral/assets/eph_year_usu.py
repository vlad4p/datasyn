"""Partitioned ingest: EPH ``usu_*`` text files under a year root → two ``gold`` tables."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
from dagster import MaterializeResult, StaticPartitionsDefinition, asset

from .._eph_year_discovery import (
    eph_year_root,
    find_usu_txt,
    partition_keys_for_year,
    quarter_num_from_key,
)

SCHEMA = "gold"
TABLE_HOGAR = f"{SCHEMA}.indec_usu_hogar"
TABLE_INDIVIDUAL = f"{SCHEMA}.indec_usu_individual"


def _duckdb_path() -> str:
    return os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()


def _year_int() -> int:
    return int(os.environ.get("INDEC_EPH_YEAR", "2025"))


def _escape_sql_path(path: Path | str) -> str:
    return str(path).replace("'", "''")


def _read_csv_expr(escaped_path: str) -> str:
    return (
        f"read_csv_auto('{escaped_path}', delim=';', header=true, quote='\"', "
        "decimal_comma=true, sample_size=-1)"
    )


def _bootstrap_table(con: duckdb.DuckDBPyConnection, table: str, sample_txt: Path) -> None:
    """``CREATE TABLE IF NOT EXISTS … AS … LIMIT 0`` from a real file (INDEC ingest pattern)."""
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    src = _read_csv_expr(_escape_sql_path(sample_txt))
    con.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM {src} LIMIT 0")


def build_eph_usu_assets():
    """Build partitioned assets (quarters ``Q1``…``Q4``; disk layout checked per run)."""
    year_root = eph_year_root()
    keys = partition_keys_for_year(year_root)
    partitions = StaticPartitionsDefinition(keys)

    @asset(
        name="indec_usu_hogar",
        partitions_def=partitions,
        group_name="indec_mercado_laboral",
        description=(
            f"Ingest ``usu_hogar_*.txt`` per quarter into ``{TABLE_HOGAR}`` "
            "(all quarters share one table; rematerialize replaces ANO4/TRIMESTRE slice)."
        ),
    )
    def indec_usu_hogar(context) -> MaterializeResult:
        year = _year_int()
        qn = quarter_num_from_key(context.partition_key)
        qdir = year_root / context.partition_key
        if not qdir.is_dir():
            context.log.warning("quarter directory missing: %s", qdir)
            return MaterializeResult(metadata={"skipped": True, "reason": "missing quarter dir"})
        txt = find_usu_txt(qdir, hogar=True)
        if txt is None or not txt.is_file():
            context.log.warning("no hogar txt under %s", qdir)
            return MaterializeResult(metadata={"skipped": True, "reason": "missing file"})

        duck = _duckdb_path()
        con = duckdb.connect(duck, read_only=False)
        try:
            _bootstrap_table(con, TABLE_HOGAR, txt)
            con.execute(
                f"DELETE FROM {TABLE_HOGAR} WHERE ANO4 = {year} AND TRIMESTRE = {qn}"
            )
            ins = _read_csv_expr(_escape_sql_path(txt))
            con.execute(f"INSERT INTO {TABLE_HOGAR} SELECT * FROM {ins}")
            n = con.execute(
                f"SELECT COUNT(*) FROM {TABLE_HOGAR} WHERE ANO4 = {year} AND TRIMESTRE = {qn}"
            ).fetchone()[0]
        finally:
            con.close()

        return MaterializeResult(
            metadata={
                "duckdb_path": duck,
                "table": TABLE_HOGAR,
                "source_path": str(txt),
                "partition": context.partition_key,
                "rows_slice": int(n),
            }
        )

    @asset(
        name="indec_usu_individual",
        partitions_def=partitions,
        group_name="indec_mercado_laboral",
        description=(
            f"Ingest ``usu_individual_*.txt`` per quarter into ``{TABLE_INDIVIDUAL}`` "
            "(all quarters share one table; rematerialize replaces ANO4/TRIMESTRE slice)."
        ),
    )
    def indec_usu_individual(context) -> MaterializeResult:
        year = _year_int()
        qn = quarter_num_from_key(context.partition_key)
        qdir = year_root / context.partition_key
        if not qdir.is_dir():
            context.log.warning("quarter directory missing: %s", qdir)
            return MaterializeResult(metadata={"skipped": True, "reason": "missing quarter dir"})
        txt = find_usu_txt(qdir, hogar=False)
        if txt is None or not txt.is_file():
            context.log.warning("no individual txt under %s", qdir)
            return MaterializeResult(metadata={"skipped": True, "reason": "missing file"})

        duck = _duckdb_path()
        con = duckdb.connect(duck, read_only=False)
        try:
            _bootstrap_table(con, TABLE_INDIVIDUAL, txt)
            con.execute(
                f"DELETE FROM {TABLE_INDIVIDUAL} WHERE ANO4 = {year} AND TRIMESTRE = {qn}"
            )
            ins = _read_csv_expr(_escape_sql_path(txt))
            con.execute(f"INSERT INTO {TABLE_INDIVIDUAL} SELECT * FROM {ins}")
            n = con.execute(
                f"SELECT COUNT(*) FROM {TABLE_INDIVIDUAL} WHERE ANO4 = {year} AND TRIMESTRE = {qn}"
            ).fetchone()[0]
        finally:
            con.close()

        return MaterializeResult(
            metadata={
                "duckdb_path": duck,
                "table": TABLE_INDIVIDUAL,
                "source_path": str(txt),
                "partition": context.partition_key,
                "rows_slice": int(n),
            }
        )

    return [indec_usu_hogar, indec_usu_individual]
