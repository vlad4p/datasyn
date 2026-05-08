"""Bronze: INDEC EPH trimestral — landing files + bronze tables in DuckDB or Iceberg REST.

When ``ICEBERG_REST_ENDPOINT`` is set, TXT rows are written via DuckDB Iceberg REST attach.
Otherwise rows go to native DuckDB tables under schema ``bronze`` (same ``read_csv_auto`` ingest).

https://duckdb.org/2025/11/28/iceberg-writes-in-duckdb
https://duckdb.org/docs/current/core_extensions/iceberg/iceberg_rest_catalogs.html
"""

import os

from dagster import AssetExecutionContext, Failure, MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.iceberg_bronze_lib import materialize_bronze_from_txt
from datasyn.indec_eph_trimestral_lib import (
    BRONZE_SCHEMA,
    SOURCE_PAGE,
    TABLE_HOGAR,
    TABLE_INDIVIDUAL,
    discover_txt_paths,
    download_year_trimesters,
)


def _trim_year() -> int:
    return int(os.environ.get("INDEC_EPH_TRIMESTRAL_YEAR", "2025"))


def _trim_quarters() -> tuple[int, ...]:
    raw = (os.environ.get("INDEC_EPH_TRIMESTRAL_QUARTERS") or "").strip().lower()
    if not raw or raw == "all":
        return (1, 2, 3, 4)
    out: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        q = int(part)
        if q not in (1, 2, 3, 4):
            raise ValueError(f"invalid quarter {q!r} (expected 1–4)")
        out.append(q)
    if not out:
        return (1, 2, 3, 4)
    return tuple(sorted(set(out)))


@asset(
    group_name="bronze",
    compute_kind="download",
    description=(
        "Download INDEC EPH TXT microdatos ZIPs per quarter, unzip, mirror to MinIO "
        "when configured; layout: DATA_LOCAL_ROOT/landing/indec/eph/<year>/Q<n>/."
    ),
)
def indec_eph_trimestral_files(context: AssetExecutionContext):
    year = _trim_year()
    quarters = _trim_quarters()
    data_root = os.environ.get("DATA_LOCAL_ROOT", "/data-local")
    context.log.info(
        "indec_eph_trimestral_files start year=%s quarters=%s DATA_LOCAL_ROOT=%s",
        year,
        quarters,
        data_root,
    )
    manifest = download_year_trimesters(
        year=year,
        quarters=quarters,
        overwrite=False,
        emit=context.log.info,
    )
    ok_ds = [d for d in manifest["datasets"] if d.get("ok")]
    failed = [d for d in manifest["datasets"] if not d.get("ok")]
    return MaterializeResult(
        metadata={
            "source_portal": MetadataValue.url(SOURCE_PAGE),
            "year": year,
            "quarters": ",".join(str(q) for q in quarters),
            "succeeded": len(ok_ds),
            "failed": len(failed),
            "data_local_root": manifest["data_local_root"],
            "httpx_timeout_sec": manifest.get("httpx_timeout_sec"),
            "total_elapsed_sec": manifest.get("total_elapsed_sec"),
        }
    )


@asset(
    deps=[indec_eph_trimestral_files],
    group_name="bronze",
    compute_kind="iceberg",
    description=(
        f"Bronze ``{BRONZE_SCHEMA}.{TABLE_HOGAR}`` from ``usu_hogar_*.txt``: Iceberg REST if "
        "``ICEBERG_REST_ENDPOINT`` is set; otherwise native DuckDB table on ``DUCKDB_PATH``."
    ),
)
def indec_usu_hogar(database: DuckDBResource):
    year = _trim_year()
    paths = discover_txt_paths(year, hogar=True)
    if not paths:
        raise Failure(f"No usu_hogar_*.txt under DATA_LOCAL_ROOT for year {year}.")

    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    with database.get_connection() as con:
        out = materialize_bronze_from_txt(
            con,
            iceberg_namespace=BRONZE_SCHEMA,
            iceberg_table=TABLE_HOGAR,
            paths=paths,
        )

    rel = out.get("iceberg_fqn") or out.get("duckdb_fqn")
    return MaterializeResult(
        metadata={
            "duckdb_path": duck_path,
            "storage": out.get("storage"),
            "relation_fqn": rel,
            "iceberg_fqn": out.get("iceberg_fqn"),
            "row_count": out.get("row_count"),
            "catalog_alias": out.get("catalog_alias"),
            "source_txt_count": len(paths),
            "year": year,
        }
    )


@asset(
    deps=[indec_usu_hogar],
    group_name="bronze",
    compute_kind="iceberg",
    description=(
        f"Bronze ``{BRONZE_SCHEMA}.{TABLE_INDIVIDUAL}`` from ``usu_individual_*.txt``. "
        "Runs after hogar; uses Iceberg REST when configured, else native DuckDB."
    ),
)
def indec_usu_individual(database: DuckDBResource):
    year = _trim_year()
    paths = discover_txt_paths(year, hogar=False)
    if not paths:
        raise Failure(f"No usu_individual_*.txt under DATA_LOCAL_ROOT for year {year}.")

    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    with database.get_connection() as con:
        out = materialize_bronze_from_txt(
            con,
            iceberg_namespace=BRONZE_SCHEMA,
            iceberg_table=TABLE_INDIVIDUAL,
            paths=paths,
        )

    rel = out.get("iceberg_fqn") or out.get("duckdb_fqn")
    return MaterializeResult(
        metadata={
            "duckdb_path": duck_path,
            "storage": out.get("storage"),
            "relation_fqn": rel,
            "iceberg_fqn": out.get("iceberg_fqn"),
            "row_count": out.get("row_count"),
            "catalog_alias": out.get("catalog_alias"),
            "source_txt_count": len(paths),
            "year": year,
        }
    )
