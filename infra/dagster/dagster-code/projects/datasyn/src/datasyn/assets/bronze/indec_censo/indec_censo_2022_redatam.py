"""Bronze: INDEC Censo 2022 Base_VP — CSV en landing → ``bronze.indec_censo_2022_vp``.

Origen: MinIO ``landing/indec/censo_2022/base_vp.csv`` (generado con
``scripts/r/export_base_vp_to_csv.R`` + ``redatamx``). Por defecto el CSV es **narrow**:
``entity``, ``variable``, ``value_code``, ``value_label``, ``count``. Snapshots locales
bajo ``.../censo_2022/snapshots/``.

``read_csv_auto`` usa ``sample_size=-1`` y ``all_varchar=true`` para no perder columnas
ni forzar tipos que recorten códigos.

Si ``ICEBERG_REST_ENDPOINT`` está definido, la tabla se escribe en el catálogo Iceberg;
si no, DuckDB nativo.
"""

from __future__ import annotations

import os
import tempfile

from botocore.exceptions import BotoCoreError, ClientError
from dagster import AssetExecutionContext, Failure, MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured
from datasyn.utils.minio_client import boto3_minio_s3_client

BRONZE_SCHEMA = "bronze"
TABLE_NAME = "indec_censo_2022_vp"
DEFAULT_OBJECT_KEY = "landing/indec/censo_2022/base_vp.csv"
_OBJECT_KEY_ENV = "INDEC_CENSO_2022_VP_OBJECT_KEY"
_LOCAL_PATH_ENV = "INDEC_CENSO_2022_VP_LOCAL_PATH"


def _bucket() -> str:
    return (os.environ.get("MINIO_BUCKET") or "data-local").strip()


def _object_key() -> str:
    return (os.environ.get(_OBJECT_KEY_ENV) or DEFAULT_OBJECT_KEY).strip().lstrip("/")


def _s3_client():
    try:
        return boto3_minio_s3_client()
    except ValueError as exc:
        raise Failure(
            f"{exc} (unless INDEC_CENSO_2022_VP_LOCAL_PATH points to a file.)"
        ) from exc


def _download_csv_bytes(context: AssetExecutionContext, bucket: str, key: str) -> bytes:
    client = _s3_client()
    context.log.info("indec_censo_2022_vp fetching s3://%s/%s", bucket, key)
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


def _table_fqn(catalog_alias: str | None) -> str:
    if catalog_alias:
        return f"{catalog_alias}.{BRONZE_SCHEMA}.{TABLE_NAME}"
    return f"{BRONZE_SCHEMA}.{TABLE_NAME}"


def _ensure_schema(con, catalog_alias: str | None) -> None:
    if catalog_alias:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog_alias}.{BRONZE_SCHEMA}")
    else:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")


@asset(
    group_name="bronze",
    compute_kind="s3",
    description=(
        "Lee ``landing/indec/censo_2022/base_vp.csv`` desde MinIO (clave configurable con "
        f"{_OBJECT_KEY_ENV}) y materializa ``{BRONZE_SCHEMA}.{TABLE_NAME}`` vía "
        "``read_csv_auto``. Opcional: ``INDEC_CENSO_2022_VP_LOCAL_PATH`` = ruta absoluta al "
        "CSV para omitir MinIO en desarrollo."
    ),
)
def indec_censo_2022_vp(context, database: DuckDBResource):
    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    local_override = (os.environ.get(_LOCAL_PATH_ENV) or "").strip()

    csv_path: str | None = None
    temp_path: str | None = None
    bucket: str | None = None
    object_key: str | None = None
    source = "minio"

    if local_override:
        if not os.path.isfile(local_override):
            raise Failure(
                f"{_LOCAL_PATH_ENV}={local_override!r} is not a file. "
                "Unset it to read from MinIO instead."
            )
        csv_path = local_override
        source = "local_file"
        context.log.info("using local CSV %s", csv_path)
    else:
        bucket = _bucket()
        object_key = _object_key()
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
            fqn = _table_fqn(catalog_alias)

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
        meta = {
            "duckdb_path": duck_path,
            "source": source,
            "table": MetadataValue.text(f"{BRONZE_SCHEMA}.{TABLE_NAME}"),
            "row_count": int(row_count),
            "storage": storage,
            "iceberg_catalog_alias": catalog_alias or "",
        }
        if bucket and object_key:
            meta["minio_bucket"] = bucket
            meta["object_key"] = object_key
        if local_override:
            meta["local_path"] = local_override

        return MaterializeResult(metadata=meta)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
