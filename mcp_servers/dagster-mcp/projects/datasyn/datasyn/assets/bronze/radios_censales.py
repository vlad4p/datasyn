"""Bronze: radios censales CSV desde MinIO → ``bronze.radios_censales`` en DuckDB."""

import os
import tempfile
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dagster import AssetExecutionContext, Failure, MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

BRONZE_SCHEMA = "bronze"
TABLE_NAME = "radios_censales"
DEFAULT_OBJECT_KEY = "landing/radio_censal/radios-censales.csv"


def _object_key() -> str:
    return (os.environ.get("RADIOS_CENSALES_OBJECT_KEY") or DEFAULT_OBJECT_KEY).strip()


def _s3_client():
    endpoint = (os.environ.get("MINIO_ENDPOINT") or "").strip()
    access_key = (os.environ.get("MINIO_ACCESS_KEY") or "").strip()
    secret_key = (os.environ.get("MINIO_SECRET_KEY") or "").strip()
    if not endpoint or not access_key or not secret_key:
        raise Failure(
            "MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY must be set for radios_censales ingest."
        )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )


def _download_csv_bytes(context: AssetExecutionContext) -> tuple[bytes, str, str]:
    bucket = (os.environ.get("MINIO_BUCKET") or "data-local").strip()
    key = _object_key()
    context.log.info("radios_censales fetching s3://%s/%s", bucket, key)
    client = _s3_client()
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
    return body, bucket, key


@asset(
    group_name="bronze",
    compute_kind="s3",
    description=(
        "Lee ``landing/radio_censal/radios-censales.csv`` desde el bucket MinIO "
        "(clave configurable con RADIOS_CENSALES_OBJECT_KEY) y materializa "
        "``bronze.radios_censales`` en DuckDB vía read_csv_auto."
    ),
)
def radios_censales(context: AssetExecutionContext, database: DuckDBResource):
    body, bucket, key = _download_csv_bytes(context)
    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
        tmp.write(body)
        tmp.flush()
        csv_path = tmp.name

    try:
        with database.get_connection() as con:
            con.execute(f'CREATE SCHEMA IF NOT EXISTS "{BRONZE_SCHEMA}"')
            con.execute(f'DROP TABLE IF EXISTS "{BRONZE_SCHEMA}"."{TABLE_NAME}"')
            con.execute(
                f"""
                CREATE TABLE "{BRONZE_SCHEMA}"."{TABLE_NAME}" AS
                SELECT * FROM read_csv_auto(
                    ?,
                    header=true,
                    auto_detect=true,
                    ignore_errors=false
                )
                """,
                [csv_path],
            )
            row_count = con.execute(
                f'SELECT COUNT(*) FROM "{BRONZE_SCHEMA}"."{TABLE_NAME}"'
            ).fetchone()[0]
    finally:
        try:
            os.unlink(csv_path)
        except OSError:
            pass

    return MaterializeResult(
        metadata={
            "duckdb_path": duck_path,
            "minio_bucket": bucket,
            "object_key": key,
            "row_count": int(row_count),
            "table": MetadataValue.text(f"{BRONZE_SCHEMA}.{TABLE_NAME}"),
        }
    )
