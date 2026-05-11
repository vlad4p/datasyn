"""Bronze: CSV UCA desde MinIO → tablas ``bronze.uca_*`` (DuckDB nativo o Iceberg REST).

Origen: ``landing/indec/censo/uca/<archivo>.csv`` (``scripts/r/upload_uca_to_minio.sh`` en el proyecto datasyn).

``UCA_FILES_LOCAL_DIR`` + mismo nombre de archivo omite MinIO en desarrollo.
``read_csv_auto``: ``sample_size=-1``, ``all_varchar=true`` (igual que otros CSV bronze).
"""

from __future__ import annotations

import os
import tempfile

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dagster import AssetExecutionContext, Failure, MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured

BRONZE_SCHEMA = "bronze"
LANDING_PREFIX = (os.environ.get("UCA_LANDING_PREFIX") or "landing/indec/censo/uca").strip().strip(
    "/"
)
_LOCAL_DIR_ENV = "UCA_FILES_LOCAL_DIR"

UCA_SPECS: list[dict[str, str]] = [
    {"file": "censo.csv", "table": "uca_censo"},
    {"file": "departamentos.csv", "table": "uca_departamentos"},
    {"file": "provincias.csv", "table": "uca_provincias"},
    {
        "file": "Indicadores-hogares-radios-2022-argentina.csv",
        "table": "uca_indicadores_hogares_radios_2022_argentina",
    },
    {
        "file": "Indicadores-hogares-radios-2022-geojson-argentina.csv",
        "table": "uca_indicadores_hogares_radios_2022_geojson_argentina",
    },
]


def _bucket() -> str:
    return (os.environ.get("MINIO_BUCKET") or "data-local").strip()


def _object_key(filename: str) -> str:
    return f"{LANDING_PREFIX}/{filename}".lstrip("/")


def _s3_client():
    endpoint = (os.environ.get("MINIO_ENDPOINT") or "").strip()
    access_key = (os.environ.get("MINIO_ACCESS_KEY") or "").strip()
    secret_key = (os.environ.get("MINIO_SECRET_KEY") or "").strip()
    if not endpoint or not access_key or not secret_key:
        raise Failure(
            "MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY must be set for UCA bronze "
            f"(unless {_LOCAL_DIR_ENV} provides a local file)."
        )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )


def _download_csv_bytes(context: AssetExecutionContext, bucket: str, key: str) -> bytes:
    client = _s3_client()
    context.log.info("fetching s3://%s/%s", bucket, key)
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            raise Failure(f"Object not found: s3://{bucket}/{key}") from exc
        raise Failure(f"MinIO get_object failed: {exc}") from exc
    except BotoCoreError as exc:
        raise Failure(f"MinIO client error: {exc}") from exc
    body = resp["Body"].read()
    if not body:
        raise Failure(f"Empty object: s3://{bucket}/{key}")
    return body


def _local_override_path(filename: str) -> str | None:
    root = (os.environ.get(_LOCAL_DIR_ENV) or "").strip()
    if not root:
        return None
    p = os.path.join(root, filename)
    return p if os.path.isfile(p) else None


def _table_fqn(catalog_alias: str | None, table_name: str) -> str:
    if catalog_alias:
        return f"{catalog_alias}.{BRONZE_SCHEMA}.{table_name}"
    return f"{BRONZE_SCHEMA}.{table_name}"


def _ensure_schema(con, catalog_alias: str | None) -> None:
    if catalog_alias:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog_alias}.{BRONZE_SCHEMA}")
    else:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")


def _materialize_one(
    context: AssetExecutionContext,
    database: DuckDBResource,
    *,
    filename: str,
    table_name: str,
) -> MaterializeResult:
    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    object_key = _object_key(filename)

    csv_path: str | None = None
    temp_path: str | None = None
    bucket: str | None = None
    source = "minio"

    local_p = _local_override_path(filename)
    if local_p:
        csv_path = local_p
        source = "local_file"
        context.log.info("using %s=%s for %s", _LOCAL_DIR_ENV, local_p, filename)
    else:
        bucket = _bucket()
        body = _download_csv_bytes(context, bucket, object_key)
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            tmp.write(body)
            tmp.flush()
            temp_path = tmp.name
        csv_path = temp_path

    try:
        with database.get_connection() as con:
            catalog_alias: str | None = None
            if iceberg_publish_configured():
                try:
                    catalog_alias = attach_iceberg_catalog(con)
                    context.log.info("Iceberg catalog attached as alias=%s", catalog_alias)
                except Exception as exc:
                    context.log.warning(
                        "Iceberg attach failed (%s); falling back to native DuckDB.", exc
                    )
                    catalog_alias = None
            else:
                context.log.info(
                    "ICEBERG_REST_ENDPOINT not set — materializing in native DuckDB at %s",
                    duck_path,
                )

            _ensure_schema(con, catalog_alias)
            fqn = _table_fqn(catalog_alias, table_name)

            con.execute(f"DROP TABLE IF EXISTS {fqn}")
            con.execute(
                f"""
                CREATE TABLE {fqn} AS
                SELECT * FROM read_csv_auto(
                    ?,
                    header=true,
                    auto_detect=true,
                    sample_size=-1,
                    all_varchar=true,
                    ignore_errors=false
                )
                """,
                [csv_path],
            )
            row_count = con.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]

        storage = "iceberg_rest" if catalog_alias else "duckdb_native"
        meta: dict = {
            "duckdb_path": duck_path,
            "source": source,
            "table": MetadataValue.text(f"{BRONZE_SCHEMA}.{table_name}"),
            "row_count": int(row_count),
            "storage": storage,
            "iceberg_catalog_alias": catalog_alias or "",
            "object_key": object_key,
        }
        if bucket:
            meta["minio_bucket"] = bucket
        if local_p:
            meta["local_path"] = local_p

        return MaterializeResult(metadata=meta)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _make_uca_asset(filename: str, table_name: str):
    @asset(
        name=table_name,
        group_name="bronze",
        compute_kind="s3",
        description=(
            f"Lee ``{_object_key(filename)}`` desde MinIO y materializa "
            f"``{BRONZE_SCHEMA}.{table_name}``. Override local: {_LOCAL_DIR_ENV}."
        ),
    )
    def _uca_bronze_asset(context, database: DuckDBResource):
        return _materialize_one(context, database, filename=filename, table_name=table_name)

    _uca_bronze_asset.__name__ = table_name
    return _uca_bronze_asset


# Explicit module-level symbols so ``load_assets_from_modules`` / ``Definitions`` always
# pick them up (dynamic ``globals()`` assignment is easy to miss in some loaders / tooling).
uca_censo = _make_uca_asset("censo.csv", "uca_censo")
uca_departamentos = _make_uca_asset("departamentos.csv", "uca_departamentos")
uca_provincias = _make_uca_asset("provincias.csv", "uca_provincias")
uca_indicadores_hogares_radios_2022_argentina = _make_uca_asset(
    "Indicadores-hogares-radios-2022-argentina.csv",
    "uca_indicadores_hogares_radios_2022_argentina",
)
uca_indicadores_hogares_radios_2022_geojson_argentina = _make_uca_asset(
    "Indicadores-hogares-radios-2022-geojson-argentina.csv",
    "uca_indicadores_hogares_radios_2022_geojson_argentina",
)

__all__ = [
    "UCA_SPECS",
    "uca_censo",
    "uca_departamentos",
    "uca_provincias",
    "uca_indicadores_hogares_radios_2022_argentina",
    "uca_indicadores_hogares_radios_2022_geojson_argentina",
]
