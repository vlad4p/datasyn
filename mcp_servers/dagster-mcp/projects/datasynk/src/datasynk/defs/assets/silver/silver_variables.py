"""Silver: explode ``bronze.indec_mercado_laboral_variables.variables`` into rows."""

from __future__ import annotations

import os

from dagster import AssetKey, MaterializeResult, asset
from dagster_duckdb import DuckDBResource

from ..bronze.variables_eph import TABLE as BRONZE_TABLE

SILVER_SCHEMA = "silver"
SILVER_TABLE = f"{SILVER_SCHEMA}.indec_mercado_laboral_variables"


def _duckdb_path() -> str:
    return os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()


@asset(
    name="silver_indec_mercado_laboral_variables",
    group_name="indec_mercado_laboral",
    deps=[AssetKey("variables_eph")],
    description=(
        "Explode each JSON array element of "
        f"``{BRONZE_TABLE}.variables`` into rows in ``{SILVER_TABLE}``."
    ),
)
def silver_indec_mercado_laboral_variables(context, database: DuckDBResource) -> MaterializeResult:
    duck = _duckdb_path()
    with database.get_connection() as con:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {SILVER_SCHEMA}")
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SILVER_TABLE} (
                id INTEGER PRIMARY KEY,
                campo VARCHAR,
                longitud VARCHAR,
                tipo VARCHAR,
                descripcion VARCHAR
            )
            """
        )
        bronze_pages = con.execute(f"SELECT COUNT(*) FROM {BRONZE_TABLE}").fetchone()[0]
        if bronze_pages == 0:
            context.log.warning(
                "Bronze table %s is empty; %s will be truncated to 0 rows.",
                BRONZE_TABLE,
                SILVER_TABLE,
            )

        con.execute(f"DELETE FROM {SILVER_TABLE}")
        con.execute(
            f"""
            INSERT INTO {SILVER_TABLE} (id, campo, longitud, tipo, descripcion)
            SELECT
                row_number() OVER (
                    ORDER BY b.source_pdf, b.page_number, CAST(j.key AS INTEGER)
                ) AS id,
                json_extract_string(j.value, '$.campo')       AS campo,
                json_extract_string(j.value, '$.longitud')    AS longitud,
                json_extract_string(j.value, '$.tipo')        AS tipo,
                json_extract_string(j.value, '$.descripcion') AS descripcion
            FROM {BRONZE_TABLE} AS b,
                 json_each(b.variables) AS j
            """
        )
        rows = con.execute(f"SELECT COUNT(*) FROM {SILVER_TABLE}").fetchone()[0]
        distinct_campos = con.execute(f"SELECT COUNT(DISTINCT campo) FROM {SILVER_TABLE}").fetchone()[0]

    context.log.info(
        "silver: bronze_pages=%s silver_rows=%s distinct_campos=%s",
        bronze_pages,
        rows,
        distinct_campos,
    )
    return MaterializeResult(
        metadata={
            "duckdb_path": duck,
            "bronze_table": BRONZE_TABLE,
            "silver_table": SILVER_TABLE,
            "bronze_rows_pages": bronze_pages,
            "silver_rows_variables": rows,
            "distinct_campos": distinct_campos,
        }
    )


def build_silver_variables_assets():
    return [silver_indec_mercado_laboral_variables]
