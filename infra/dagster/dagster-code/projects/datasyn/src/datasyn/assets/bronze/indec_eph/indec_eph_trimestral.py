"""Bronze: INDEC EPH trimestral — landing files + bronze tables in DuckDB or Iceberg REST.

When ``ICEBERG_REST_ENDPOINT`` is set, TXT rows are written via DuckDB Iceberg REST attach.
Otherwise rows go to native DuckDB tables under schema ``bronze`` (``read_csv_auto`` on
semicolon-separated INDEC TXT).

Assets: ``indec_eph_trimestral_files`` (download/unzip/MinIO mirror) → ``indec_usu_hogar`` →
``indec_usu_individual`` (ordered dependency chain).

https://duckdb.org/2025/11/28/iceberg-writes-in-duckdb
https://duckdb.org/docs/current/core_extensions/iceberg/iceberg_rest_catalogs.html
"""

from __future__ import annotations

import os

from dagster import Failure, MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.utils.iceberg import materialize_from_paths
from datasyn.assets.bronze.indec_eph.indec_eph_trimestral_lib import (
    BRONZE_SCHEMA,
    SOURCE_PAGE,
    TABLE_HOGAR,
    TABLE_INDIVIDUAL,
    discover_txt_paths,
    download_year_trimesters,
    read_csv_auto_sql,
)


def _trim_year() -> int:
    return int(os.environ.get("INDEC_EPH_TRIMESTRAL_YEAR", "2025"))


def _trim_quarters() -> tuple[int, ...]:
    raw = (os.environ.get("INDEC_EPH_TRIMESTRAL_QUARTERS") or "").strip().lower()
    if not raw or raw == "all":
        return (1, 2, 3, 4)
    quarters: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        q = int(part)
        if q not in (1, 2, 3, 4):
            raise ValueError(f"invalid quarter {q!r} (expected 1–4)")
        quarters.add(q)
    return tuple(sorted(quarters)) or (1, 2, 3, 4)


@asset(
    group_name="bronze",
    compute_kind="download",
    description=(
        "Download INDEC EPH TXT microdatos ZIPs per quarter, unzip, mirror to MinIO "
        "when configured; layout: DATA_LOCAL_ROOT/landing/indec/eph/<year>/Q<n>/."
    ),
)
def indec_eph_trimestral_files(context):
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


def _materialize_txt_table(
    database: DuckDBResource,
    *,
    year: int,
    table: str,
    hogar: bool,
) -> MaterializeResult:
    paths = discover_txt_paths(year, hogar=hogar)
    if not paths:
        pattern = "usu_hogar_*.txt" if hogar else "usu_individual_*.txt"
        raise Failure(f"No {pattern} under DATA_LOCAL_ROOT for year {year}.")

    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    with database.get_connection() as con:
        out = materialize_from_paths(
            con,
            namespace=BRONZE_SCHEMA,
            table=table,
            paths=paths,
            read_relation_sql=read_csv_auto_sql,
        )

    return MaterializeResult(
        metadata={
            "duckdb_path": duck_path,
            "storage": out.get("storage"),
            "relation_fqn": out.get("iceberg_fqn") or out.get("duckdb_fqn"),
            "iceberg_fqn": out.get("iceberg_fqn"),
            "row_count": out.get("row_count"),
            "catalog_alias": out.get("catalog_alias"),
            "source_txt_count": len(paths),
            "year": year,
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
    return _materialize_txt_table(database, year=_trim_year(), table=TABLE_HOGAR, hogar=True)


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
    return _materialize_txt_table(database, year=_trim_year(), table=TABLE_INDIVIDUAL, hogar=False)
