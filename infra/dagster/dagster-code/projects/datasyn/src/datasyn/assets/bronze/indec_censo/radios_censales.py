"""Bronze: radios censales CSV desde MinIO → ``bronze.radios_censales`` en DuckDB o Iceberg REST.

Misma ruta de ingest que ``indec_censo_2022_redatam``: ``read_csv_auto`` con
``sample_size=-1`` y ``all_varchar=true``; si ``ICEBERG_REST_ENDPOINT`` está definido,
se adjunta el catálogo y la tabla vive bajo el alias Iceberg.

Override local: ``RADIOS_CENSALES_LOCAL_PATH`` (archivo absoluto) omite MinIO.
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
TABLE_NAME = "radios_censales"
DEFAULT_OBJECT_KEY = "landing/radio_censal/radios-censales.csv"
_OBJECT_KEY_ENV = "RADIOS_CENSALES_OBJECT_KEY"
_LOCAL_PATH_ENV = "RADIOS_CENSALES_LOCAL_PATH"


def _bucket() -> str:
    return (os.environ.get("MINIO_BUCKET") or "data-local").strip()


def _object_key() -> str:
    return (os.environ.get(_OBJECT_KEY_ENV) or DEFAULT_OBJECT_KEY).strip().lstrip("/")


def _s3_client():
    endpoint = (os.environ.get("MINIO_ENDPOINT") or "").strip()
    access_key = (os.environ.get("MINIO_ACCESS_KEY") or "").strip()
    secret_key = (os.environ.get("MINIO_SECRET_KEY") or "").strip()
    if not endpoint or not access_key or not secret_key:
        raise Failure(
            "MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY must be set for radios_censales "
            f"(unless {_LOCAL_PATH_ENV} points to a file)."
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
    context.log.info("radios_censales fetching s3://%s/%s", bucket, key)
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
        "Lee ``landing/radio_censal/radios-censales.csv`` desde MinIO "
        f"(clave {_OBJECT_KEY_ENV}) y materializa ``{BRONZE_SCHEMA}.{TABLE_NAME}``. "
        f"Override local: {_LOCAL_PATH_ENV}. Iceberg si ``ICEBERG_REST_ENDPOINT``."
    ),
)
def radios_censales(context, database: DuckDBResource):
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
        meta: dict = {
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
