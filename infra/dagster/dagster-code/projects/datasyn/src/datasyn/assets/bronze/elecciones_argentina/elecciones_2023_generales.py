"""Elecciones Argentina 2023 — ZIP en MinIO, CSV en ``bronze.resultado_electorales_2023_generales``.

Fuente: https://www.argentina.gob.ar/sites/default/files/2023_generales_1.zip

- ``elecciones_argentina_2023_generales_landing``: descarga el ZIP, lo sube como
  ``landing/elecciones_argentina/2023_generales_1.zip``, descomprime bajo
  ``landing/elecciones_argentina/2023_generales_1/`` y sincroniza ese árbol a MinIO.
- ``resultado_electorales_2023_generales``: lee
  ``ResultadoElectorales_2023_Generales.csv`` desde MinIO (o ruta local bajo
  ``DATA_LOCAL_ROOT``) y materializa la tabla bronze.

Override local (sin MinIO): ``ELECCIONES_ARGENTINA_2023_LOCAL_CSV`` apunta al CSV.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import httpx
from botocore.exceptions import BotoCoreError, ClientError
from dagster import AssetExecutionContext, Failure, MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.assets.bronze.indec_eph.indec_eph_trimestral_lib import (
    data_local_root,
    download_zip,
    safe_unzip,
    sync_tree_to_minio,
)
from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured
from datasyn.utils.minio_client import boto3_minio_s3_client

BRONZE_SCHEMA = "bronze"
TABLE_NAME = "resultado_electorales_2023_generales"
CSV_FILENAME = "ResultadoElectorales_2023_Generales.csv"
ZIP_FILENAME = "2023_generales_1.zip"
DEFAULT_URL = (
    "https://www.argentina.gob.ar/sites/default/files/2023_generales_1.zip"
)
LANDING_SUBDIR = Path("landing/elecciones_argentina")
EXTRACT_DIRNAME = "2023_generales_1"


def _bucket() -> str:
    return (os.environ.get("MINIO_BUCKET") or "data-local").strip()


def _quote_ident(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _s3_key_for_path_under_data_local(local_path: Path) -> str:
    root = data_local_root().resolve()
    rel = local_path.resolve().relative_to(root).as_posix().lstrip("/")
    prefix = (os.environ.get("MINIO_PREFIX") or "").strip().strip("/")
    return f"{prefix}/{rel}" if prefix else rel


def _upload_file_to_minio(context: AssetExecutionContext, local_file: Path) -> str | None:
    try:
        client = boto3_minio_s3_client()
    except ValueError as exc:
        context.log.warning("MinIO no configurado, omitiendo subida del ZIP: %s", exc)
        return None
    bucket = _bucket()
    key = _s3_key_for_path_under_data_local(local_file)
    context.log.info("put_object s3://%s/%s <- %s", bucket, key, local_file)
    try:
        client.upload_file(str(local_file), bucket, key)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise Failure(f"MinIO upload_file failed s3://{bucket}/{key}: {exc}") from exc
    return key


def _work_dir() -> Path:
    return data_local_root() / LANDING_SUBDIR


def _zip_path() -> Path:
    return _work_dir() / ZIP_FILENAME


def _extract_dir() -> Path:
    return _work_dir() / EXTRACT_DIRNAME


def _csv_local_path() -> Path:
    return _extract_dir() / CSV_FILENAME


def resolve_csv_under_extract_dir(extract_root: Path) -> Path | None:
    """``extract_root/Resultado….csv`` o primera coincidencia recursiva por nombre."""
    direct = extract_root / CSV_FILENAME
    if direct.is_file():
        return direct
    for p in sorted(extract_root.rglob(CSV_FILENAME)):
        if p.is_file():
            return p
    return None


def _source_url() -> str:
    return (os.environ.get("ELECCIONES_ARGENTINA_2023_URL") or DEFAULT_URL).strip()


@asset(
    group_name="bronze",
    compute_kind="download",
    description=(
        "Descarga 2023_generales_1.zip, lo guarda en MinIO como "
        "landing/elecciones_argentina/2023_generales_1.zip, descomprime en "
        "landing/elecciones_argentina/2023_generales_1/ y sincroniza el directorio a MinIO."
    ),
)
def elecciones_argentina_2023_generales_landing(context):
    work = _work_dir()
    work.mkdir(parents=True, exist_ok=True)
    zp = _zip_path()
    ex = _extract_dir()
    url = _source_url()
    overwrite = os.environ.get("ELECCIONES_ARGENTINA_2023_OVERWRITE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    timeout_s = float(os.environ.get("ELECCIONES_ARGENTINA_2023_DOWNLOAD_TIMEOUT_S", "3600"))
    with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
        dl = download_zip(client, url, zp, overwrite=overwrite, emit=context.log.info)

    zip_key = _upload_file_to_minio(context, zp)

    if ex.exists() and overwrite:
        shutil.rmtree(ex)
    ex.mkdir(parents=True, exist_ok=True)
    unzipped = safe_unzip(zp, ex, emit=context.log.info)

    csv_resolved = resolve_csv_under_extract_dir(ex)
    if csv_resolved is None:
        raise Failure(
            f"Tras descomprimir no se encontró {CSV_FILENAME!r} bajo {ex}. "
            f"Archivos extraídos ({len(unzipped)}): {unzipped[:20]}{'…' if len(unzipped) > 20 else ''}"
        )

    sync_res = sync_tree_to_minio(ex, root=data_local_root(), emit=context.log.info)

    return MaterializeResult(
        metadata={
            "source_url": MetadataValue.url(url),
            "zip_path": MetadataValue.text(str(zp)),
            "zip_s3_key": zip_key or "(skipped)",
            "extract_dir": MetadataValue.text(str(ex)),
            "csv_path": MetadataValue.text(str(csv_resolved)),
            "unzipped_count": len(unzipped),
            "minio_sync": MetadataValue.json(sync_res),
            "sha256": dl.get("sha256", "")[:16] + "…",
            "from_cache": dl.get("from_cache", False),
        }
    )


def _download_csv_bytes(context: AssetExecutionContext, bucket: str, key: str) -> bytes:
    client = boto3_minio_s3_client()
    context.log.info("get_object s3://%s/%s", bucket, key)
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


def _table_fqn(catalog_alias: str | None, table_name: str) -> str:
    qt = _quote_ident(table_name)
    if catalog_alias:
        return f"{catalog_alias}.{BRONZE_SCHEMA}.{qt}"
    return f"{BRONZE_SCHEMA}.{qt}"


def _ensure_schema(con, catalog_alias: str | None) -> None:
    if catalog_alias:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog_alias}.{BRONZE_SCHEMA}")
    else:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")


@asset(
    deps=[elecciones_argentina_2023_generales_landing],
    group_name="bronze",
    compute_kind="s3",
    description=(
        f"Lee ``{LANDING_SUBDIR.as_posix()}/{EXTRACT_DIRNAME}/{CSV_FILENAME}`` desde MinIO "
        f"(o ``ELECCIONES_ARGENTINA_2023_LOCAL_CSV``) y crea ``{BRONZE_SCHEMA}.{TABLE_NAME}``."
    ),
)
def resultado_electorales_2023_generales(context, database: DuckDBResource):
    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    local_override = (os.environ.get("ELECCIONES_ARGENTINA_2023_LOCAL_CSV") or "").strip()

    csv_path: str | None = None
    temp_path: str | None = None
    bucket: str | None = None
    source = "minio"
    local_csv = resolve_csv_under_extract_dir(_extract_dir())
    object_key = (
        _s3_key_for_path_under_data_local(local_csv)
        if local_csv is not None
        else _s3_key_for_path_under_data_local(_csv_local_path())
    )

    if local_override:
        p = Path(local_override)
        if not p.is_file():
            raise Failure(f"ELECCIONES_ARGENTINA_2023_LOCAL_CSV no es archivo: {p}")
        csv_path = str(p.resolve())
        source = "local_override"
        context.log.info("using ELECCIONES_ARGENTINA_2023_LOCAL_CSV=%s", csv_path)
    elif local_csv is not None and local_csv.is_file():
        csv_path = str(local_csv.resolve())
        source = "data_local"
        context.log.info("using DATA_LOCAL CSV at %s", csv_path)
    else:
        bucket = _bucket()
        try:
            body = _download_csv_bytes(context, bucket, object_key)
        except Failure:
            raise
        except ValueError as exc:
            raise Failure(
                f"{exc} Configure MinIO or place the CSV under {_csv_local_path()} "
                "or set ELECCIONES_ARGENTINA_2023_LOCAL_CSV."
            ) from exc
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
                        "Iceberg attach failed (%s); falling back to native DuckDB.", exc
                    )
                    catalog_alias = None
            else:
                context.log.info(
                    "ICEBERG_REST_ENDPOINT not set — materializing in native DuckDB at %s",
                    duck_path,
                )

            _ensure_schema(con, catalog_alias)
            fqn = _table_fqn(catalog_alias, TABLE_NAME)

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
            "object_key": object_key,
        }
        if bucket:
            meta["minio_bucket"] = bucket
        return MaterializeResult(metadata=meta)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


__all__ = [
    "elecciones_argentina_2023_generales_landing",
    "resultado_electorales_2023_generales",
]
