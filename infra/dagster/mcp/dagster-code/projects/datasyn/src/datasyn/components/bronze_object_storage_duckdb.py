"""Bronze ingest: MinIO (S3-compatible object storage) → DuckDB.

Spec-driven assets aligned with Dagster Components-style pipelines
(https://docs.dagster.io/guides/build/components): define a
:class:`BronzeMinioDuckdbSpec` (or a small list of them) and call
:func:`make_bronze_minio_duckdb_asset` once per table.

Default target schema is ``bronze``. Optional Iceberg REST publishing uses the
same attach path as legacy bronze assets (``datasyn.utils.iceberg``).
"""

import os
import tempfile
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from dagster import AssetExecutionContext, Failure, MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured
from datasyn.utils.minio_client import boto3_minio_s3_client

DEFAULT_BRONZE_SCHEMA = "bronze"


def _bucket() -> str:
    return (os.environ.get("MINIO_BUCKET") or "data-local").strip()


def _quote_ident(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _s3_client():
    try:
        return boto3_minio_s3_client()
    except ValueError as exc:
        raise Failure(f"{exc}") from exc


def _download_object_bytes(context: AssetExecutionContext, bucket: str, key: str) -> bytes:
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


def _local_override_path(local_root_env: str, filename: str) -> str | None:
    root = (os.environ.get(local_root_env) or "").strip()
    if not root:
        return None
    p = os.path.join(root, filename)
    return p if os.path.isfile(p) else None


def _normalize_object_key(key: str) -> str:
    return key.strip().lstrip("/")


def _table_fqn(catalog_alias: str | None, schema_name: str, table_name: str) -> str:
    qs = _quote_ident(schema_name)
    qt = _quote_ident(table_name)
    if catalog_alias:
        return f"{catalog_alias}.{qs}.{qt}"
    return f"{qs}.{qt}"


def _ensure_schema(con: Any, catalog_alias: str | None, schema_name: str) -> None:
    qs = _quote_ident(schema_name)
    if catalog_alias:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog_alias}.{qs}")
    else:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {qs}")


@dataclass(frozen=True)
class BronzeMinioDuckdbSpec:
    """Declarative descriptor for one object → bronze table load."""

    #: Dagster asset name (and default DuckDB table base name).
    asset_name: str
    #: Full object key inside ``MINIO_BUCKET`` (e.g. ``landing/foo/bar.csv``).
    object_key: str
    #: DuckDB schema (default ``bronze``).
    schema_name: str = DEFAULT_BRONZE_SCHEMA
    #: Table name; defaults to ``asset_name``.
    table_name: str | None = None
    group_name: str = "bronze"
    compute_kind: str = "s3"
    description: str | None = None
    #: If set, ``os.environ[local_override_env]/<local_filename>`` skips MinIO when present.
    local_override_env: str | None = None
    #: Basename under the local override directory (defaults to last segment of ``object_key``).
    local_filename: str | None = None
    read_csv_header: bool = True
    read_csv_auto_detect: bool = True
    read_csv_sample_size: int = -1
    read_csv_all_varchar: bool = True
    read_csv_ignore_errors: bool = False


def materialize_bronze_from_minio(
    context: AssetExecutionContext,
    database: DuckDBResource,
    spec: BronzeMinioDuckdbSpec,
) -> MaterializeResult:
    """Download one object (unless local override), load via ``read_csv_auto``, optional Iceberg."""
    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    table = spec.table_name or spec.asset_name
    object_key = _normalize_object_key(spec.object_key)
    local_name = spec.local_filename or os.path.basename(object_key.rstrip("/"))

    csv_path: str | None = None
    temp_path: str | None = None
    bucket: str | None = None
    source = "minio"
    local_p: str | None = None

    if spec.local_override_env:
        local_p = _local_override_path(spec.local_override_env, local_name)
    if local_p:
        csv_path = local_p
        source = "local_file"
        context.log.info(
            "using %s=%s for %s",
            spec.local_override_env,
            local_p,
            local_name,
        )
    else:
        bucket = _bucket()
        body = _download_object_bytes(context, bucket, object_key)
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            tmp.write(body)
            tmp.flush()
            temp_path = tmp.name
        csv_path = temp_path

    assert csv_path is not None

    try:
        with database.get_connection() as con:
            catalog_alias: str | None = None
            if iceberg_publish_configured():
                try:
                    catalog_alias = attach_iceberg_catalog(con)
                    context.log.info("Iceberg catalog attached as alias=%s", catalog_alias)
                except Exception as exc:
                    context.log.warning(
                        "Iceberg attach failed (%s); falling back to native DuckDB.",
                        exc,
                    )
                    catalog_alias = None
            else:
                context.log.info(
                    "ICEBERG_REST_ENDPOINT not set — materializing in native DuckDB at %s",
                    duck_path,
                )

            _ensure_schema(con, catalog_alias, spec.schema_name)
            fqn = _table_fqn(catalog_alias, spec.schema_name, table)

            con.execute(f"DROP TABLE IF EXISTS {fqn}")
            con.execute(
                f"""
                CREATE TABLE {fqn} AS
                SELECT * FROM read_csv_auto(
                    ?,
                    header=?,
                    auto_detect=?,
                    sample_size=?,
                    all_varchar=?,
                    ignore_errors=?
                )
                """,
                [
                    csv_path,
                    spec.read_csv_header,
                    spec.read_csv_auto_detect,
                    spec.read_csv_sample_size,
                    spec.read_csv_all_varchar,
                    spec.read_csv_ignore_errors,
                ],
            )
            row_count = con.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]

        storage = "iceberg_rest" if catalog_alias else "duckdb_native"
        meta: dict[str, Any] = {
            "duckdb_path": duck_path,
            "source": source,
            "table": MetadataValue.text(f"{spec.schema_name}.{table}"),
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


def make_bronze_minio_duckdb_asset(spec: BronzeMinioDuckdbSpec):
    """Return a Dagster ``@asset`` bound to *spec* (module-level assignment recommended)."""

    table = spec.table_name or spec.asset_name
    object_key = _normalize_object_key(spec.object_key)
    default_desc = (
        f"Lee ``{object_key}`` desde MinIO y materializa ``{spec.schema_name}.{table}``."
    )
    if spec.local_override_env:
        default_desc += f" Override local: {spec.local_override_env}."

    @asset(
        name=spec.asset_name,
        group_name=spec.group_name,
        compute_kind=spec.compute_kind,
        description=spec.description or default_desc,
    )
    def _bronze_minio_asset(context: AssetExecutionContext, database: DuckDBResource):
        return materialize_bronze_from_minio(context, database, spec)

    _bronze_minio_asset.__name__ = spec.asset_name
    return _bronze_minio_asset


__all__ = [
    "BronzeMinioDuckdbSpec",
    "DEFAULT_BRONZE_SCHEMA",
    "make_bronze_minio_duckdb_asset",
    "materialize_bronze_from_minio",
]
