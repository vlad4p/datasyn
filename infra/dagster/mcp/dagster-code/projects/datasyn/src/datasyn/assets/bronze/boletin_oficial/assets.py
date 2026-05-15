"""Boletín Oficial — tercera sección (contrataciones): portada → MinIO (PDF/HTML/manifest) → bronze."""

import json
import os
import time
from datetime import date, datetime, timezone
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from dagster import (
    AssetExecutionContext,
    DailyPartitionsDefinition,
    Failure,
    MaterializeResult,
    MetadataValue,
    asset,
)
from dagster_duckdb import DuckDBResource

from datasyn.assets.bronze.boletin_oficial.lib import (
    fetch_aviso_pdf_bytes,
    fetch_detalle_html,
    fetch_section_index_html,
    parse_tercera_index,
    ymd_from_date,
)
from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured
from datasyn.utils.minio_client import boto3_minio_s3_client

BRONZE_SCHEMA = "bronze"
TABLE_NAME = "boa_tercera_contrataciones_avisos"
LANDING_PREFIX = "landing/boa/tercera/contrataciones"

BOA_TERCERA_DAILY = DailyPartitionsDefinition(
    start_date=datetime(2024, 1, 1),
    end_offset=1,
)


def _bucket() -> str:
    return (os.environ.get("MINIO_BUCKET") or "data-local").strip()


def _s3():
    try:
        return boto3_minio_s3_client()
    except ValueError as exc:
        raise Failure(str(exc)) from exc


def _partition_date(context: AssetExecutionContext) -> date:
    return date.fromisoformat(context.partition_key)


def _date_path(d: date) -> str:
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def _landing_dir_for_partition(d: date) -> str:
    return f"{LANDING_PREFIX}/{_date_path(d)}"


def _sleep_s() -> float:
    return float(os.environ.get("BOA_DOWNLOAD_SLEEP_S", "0.35"))


def _skip_pdf() -> bool:
    return os.environ.get("BOA_SKIP_PDF", "").strip().lower() in {"1", "true", "yes"}


def _table_fqn(catalog_alias: str | None) -> str:
    if catalog_alias:
        return f"{catalog_alias}.{BRONZE_SCHEMA}.{TABLE_NAME}"
    return f"{BRONZE_SCHEMA}.{TABLE_NAME}"


def _ensure_table(con: Any, fqn: str) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {fqn} (
            edicion_fecha DATE,
            rubro VARCHAR,
            aviso_id VARCHAR,
            fecha_publicacion_ymd VARCHAR,
            organismo VARCHAR,
            detalle VARCHAR,
            detalle_url VARCHAR,
            pdf_landing_key VARCHAR,
            html_landing_key VARCHAR,
            scraped_at TIMESTAMP
        );
        """
    )


@asset(
    partitions_def=BOA_TERCERA_DAILY,
    group_name="bronze",
    compute_kind="python",
    description=(
        "Descarga la portada ``/seccion/tercera/YYYYMMDD`` (contrataciones), identifica rubros "
        f"``h5.seccion-rubro``, sube PDF + HTML por aviso y ``manifest.json`` a MinIO bajo "
        f"``{LANDING_PREFIX}/YYYY/MM/DD/``."
    ),
)
def boa_tercera_contrataciones_landing(context: AssetExecutionContext) -> MaterializeResult:
    day = _partition_date(context)
    ymd = ymd_from_date(day)
    prefix = _landing_dir_for_partition(day)
    scraped_at = datetime.now(timezone.utc)

    html_index = fetch_section_index_html(ymd=ymd)
    items = parse_tercera_index(html_index)
    context.log.info("BOA tercera %s: %d avisos en índice", ymd, len(items))

    client = _s3()
    bucket = _bucket()
    sleep_s = _sleep_s()
    skip_pdf = _skip_pdf()

    pdf_ok = 0
    html_ok = 0
    errors: list[str] = []

    for it in items:
        pdf_key = f"{prefix}/{it.aviso_id}.pdf"
        html_key = f"{prefix}/{it.aviso_id}.html"
        if not skip_pdf:
            try:
                pdf_bytes = fetch_aviso_pdf_bytes(
                    aviso_id=it.aviso_id,
                    fecha_publicacion_ymd=it.fecha_publicacion_ymd,
                )
                client.put_object(
                    Bucket=bucket,
                    Key=pdf_key,
                    Body=pdf_bytes,
                    ContentType="application/pdf",
                )
                pdf_ok += 1
            except Exception as exc:
                msg = f"pdf {it.aviso_id}: {type(exc).__name__}: {exc}"
                context.log.warning(msg)
                errors.append(msg)
        try:
            det_html = fetch_detalle_html(detalle_url=it.detalle_url)
            client.put_object(
                Bucket=bucket,
                Key=html_key,
                Body=det_html.encode("utf-8"),
                ContentType="text/html; charset=utf-8",
            )
            html_ok += 1
        except Exception as exc:
            msg = f"html {it.aviso_id}: {type(exc).__name__}: {exc}"
            context.log.warning(msg)
            errors.append(msg)
        time.sleep(sleep_s)

    manifest_key = f"{prefix}/manifest.json"
    enriched: list[dict[str, Any]] = []
    for it in items:
        row = {
            "rubro": it.rubro,
            "aviso_id": it.aviso_id,
            "fecha_publicacion_ymd": it.fecha_publicacion_ymd,
            "organismo": it.organismo,
            "detalle": it.detalle,
            "detalle_url": it.detalle_url,
            "pdf_landing_key": f"{prefix}/{it.aviso_id}.pdf",
            "html_landing_key": f"{prefix}/{it.aviso_id}.html",
        }
        enriched.append(row)

    client.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(enriched, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )

    return MaterializeResult(
        metadata={
            "partition": context.partition_key,
            "ymd": ymd,
            "avisos_indexados": len(items),
            "pdf_subidos": pdf_ok,
            "html_subidos": html_ok,
            "minio_bucket": bucket,
            "manifest_key": manifest_key,
            "errores_muestra": MetadataValue.json(errors[:15]),
            "boa_skip_pdf": skip_pdf,
        }
    )


@asset(
    deps=[boa_tercera_contrataciones_landing],
    partitions_def=BOA_TERCERA_DAILY,
    group_name="bronze",
    compute_kind="duckdb",
    description=(
        f"Lee ``manifest.json`` de MinIO para la partición y materializa ``{BRONZE_SCHEMA}.{TABLE_NAME}`` "
        "(reemplazo del día; Iceberg si está configurado)."
    ),
)
def boa_tercera_contrataciones_bronze(
    context: AssetExecutionContext, database: DuckDBResource
) -> MaterializeResult:
    day = _partition_date(context)
    prefix = _landing_dir_for_partition(day)
    manifest_key = f"{prefix}/manifest.json"

    client = _s3()
    bucket = _bucket()
    try:
        resp = client.get_object(Bucket=bucket, Key=manifest_key)
        raw = resp["Body"].read()
    except (ClientError, BotoCoreError) as exc:
        raise Failure(f"No manifest at s3://{bucket}/{manifest_key}: {exc}") from exc

    enriched = json.loads(raw.decode("utf-8"))
    scraped_at = datetime.now(timezone.utc)
    rows: list[tuple[Any, ...]] = []
    for row in enriched:
        rows.append(
            (
                day,
                str(row.get("rubro") or ""),
                str(row.get("aviso_id") or ""),
                str(row.get("fecha_publicacion_ymd") or ""),
                str(row.get("organismo") or ""),
                str(row.get("detalle") or ""),
                str(row.get("detalle_url") or ""),
                str(row.get("pdf_landing_key") or ""),
                str(row.get("html_landing_key") or ""),
                scraped_at,
            )
        )

    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    with database.get_connection() as con:
        catalog_alias: str | None = None
        if iceberg_publish_configured():
            try:
                catalog_alias = attach_iceberg_catalog(con)
            except Exception as exc:
                context.log.warning("Iceberg attach failed (%s); native DuckDB.", exc)
                catalog_alias = None
        if catalog_alias:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog_alias}.{BRONZE_SCHEMA}")
        else:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {BRONZE_SCHEMA}")
        fqn = _table_fqn(catalog_alias)
        _ensure_table(con, fqn)
        con.execute(
            f"""
            DELETE FROM {fqn}
            WHERE edicion_fecha = DATE '{context.partition_key}';
            """
        )
        if rows:
            con.executemany(
                f"""
                INSERT INTO {fqn}
                (edicion_fecha, rubro, aviso_id, fecha_publicacion_ymd, organismo, detalle,
                 detalle_url, pdf_landing_key, html_landing_key, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                rows,
            )
        cnt = con.execute(f"SELECT COUNT(*) FROM {fqn}").fetchone()[0]

    return MaterializeResult(
        metadata={
            "partition": context.partition_key,
            "rows_inserted": len(rows),
            "table_rows_total": int(cnt),
            "duckdb_path": duck_path,
            "fqn": MetadataValue.text(fqn),
            "storage": "iceberg_rest" if catalog_alias else "duckdb_native",
        }
    )
