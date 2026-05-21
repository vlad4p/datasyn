"""La Nación Opinión: columnistas (perfil) + notas enlazadas por ``columnista_id``.

Flujo alineado a noticias: scrape particionado por día (filtro ``-nidDDMMYYYY`` en URLs
``/opinion/...``) → MinIO ``landing/lanacion/opinion/`` → tablas
``bronze.lanacion_opinion_columnistas`` y ``bronze.lanacion_opinion_notas``.
"""

import os
from datetime import date, datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError
from dagster import (
    AssetExecutionContext,
    Failure,
    MaterializeResult,
    MetadataValue,
    asset,
)
from dagster_duckdb import DuckDBResource

from datasyn.assets.bronze.lanacion.assets import LAN_DAILY, _parse_frontmatter
from datasyn.assets.bronze.lanacion.opinion_lib import (
    build_columnist_markdown,
    build_opinion_markdown,
    scrape_opinion_partition,
)
from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured
from datasyn.utils.minio_client import boto3_minio_s3_client

BRONZE_SCHEMA = "bronze"
TABLE_COLUMNISTAS = "lanacion_opinion_columnistas"
TABLE_OPINIONES = "lanacion_opinion_notas"


def _bucket() -> str:
    return (os.environ.get("MINIO_BUCKET") or "data-local").strip()


def _s3():
    try:
        return boto3_minio_s3_client()
    except ValueError as exc:
        raise Failure(str(exc)) from exc


def _partition_date(context: AssetExecutionContext) -> date:
    return date.fromisoformat(context.partition_key)


def _fqn(catalog_alias: str | None, table: str) -> str:
    if catalog_alias:
        return f"{catalog_alias}.{BRONZE_SCHEMA}.{table}"
    return f"{BRONZE_SCHEMA}.{table}"


def _ensure_columnistas(con, fqn: str) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {fqn} (
            columnista_id BIGINT,
            nombre VARCHAR,
            autor_url VARCHAR,
            slug VARCHAR,
            perfil_politico VARCHAR,
            scraped_at TIMESTAMP,
            landing_key VARCHAR
        );
        """
    )


def _ensure_opiniones(con, fqn: str) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {fqn} (
            columnista_id BIGINT,
            titulo VARCHAR,
            url VARCHAR,
            cuerpo_md VARCHAR,
            fecha_publicacion TIMESTAMP,
            scraped_at TIMESTAMP,
            landing_key VARCHAR,
            tema VARCHAR
        );
        """
    )


@asset(
    partitions_def=LAN_DAILY,
    group_name="bronze",
    compute_kind="python",
    description=(
        "Scrape hub columnistas La Nación, fichas de autor (perfil / biografía) y notas "
        "``/opinion/...-nidDDMMYYYY/`` del día de partición; sube markdown a "
        "``landing/lanacion/opinion/`` en MinIO."
    ),
)
def lanacion_opinion_landing_markdown(context: AssetExecutionContext) -> MaterializeResult:
    day = _partition_date(context)
    context.log.info("lanacion opinion scrape partition=%s", context.partition_key)
    columnists, opinions = scrape_opinion_partition(partition_day=day)
    client = _s3()
    bucket = _bucket()
    scraped_at = datetime.now(timezone.utc)
    keys: list[str] = []
    n_col, n_op = 0, 0
    for c in columnists:
        body = build_columnist_markdown(c, scraped_at)
        try:
            client.put_object(
                Bucket=bucket,
                Key=c.landing_key,
                Body=body.encode("utf-8"),
                ContentType="text/markdown; charset=utf-8",
            )
            keys.append(c.landing_key)
            n_col += 1
        except (ClientError, BotoCoreError) as exc:
            context.log.error("put_object failed %s: %s", c.landing_key, exc)
            raise Failure(f"MinIO put failed: {exc}") from exc
    for o in opinions:
        body = build_opinion_markdown(o, scraped_at)
        try:
            client.put_object(
                Bucket=bucket,
                Key=o.landing_key,
                Body=body.encode("utf-8"),
                ContentType="text/markdown; charset=utf-8",
            )
            keys.append(o.landing_key)
            n_op += 1
        except (ClientError, BotoCoreError) as exc:
            context.log.error("put_object failed %s: %s", o.landing_key, exc)
            raise Failure(f"MinIO put failed: {exc}") from exc

    return MaterializeResult(
        metadata={
            "partition": context.partition_key,
            "columnistas_written": n_col,
            "opiniones_written": n_op,
            "minio_bucket": bucket,
            "sample_keys": MetadataValue.json(keys[:30]),
        }
    )


@asset(
    deps=[lanacion_opinion_landing_markdown],
    partitions_def=LAN_DAILY,
    group_name="bronze",
    compute_kind="duckdb",
    description=(
        "Lee ``landing/lanacion/opinion/columnistas/*.md`` y "
        "``landing/lanacion/opinion/articulos/*/YYYY/MM/DD/*.md`` para la partición; "
        f"actualiza ``{BRONZE_SCHEMA}.{TABLE_COLUMNISTAS}`` (refresh) y "
        f"``{BRONZE_SCHEMA}.{TABLE_OPINIONES}`` (reemplazo por fecha)."
    ),
)
def lanacion_opinion_bronze(context: AssetExecutionContext, database: DuckDBResource) -> MaterializeResult:
    day = _partition_date(context)
    y, m, dd = day.year, day.month, day.day
    date_segment = f"/{y:04d}/{m:02d}/{dd:02d}/"
    client = _s3()
    bucket = _bucket()
    paginator = client.get_paginator("list_objects_v2")

    rows_col: list[tuple] = []
    prefix_col = "landing/lanacion/opinion/columnistas/"
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix_col):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if not key.endswith(".md"):
                continue
            try:
                resp = client.get_object(Bucket=bucket, Key=key)
                raw = resp["Body"].read().decode("utf-8", errors="replace")
            except (ClientError, BotoCoreError) as exc:
                context.log.warning("skip read %s: %s", key, exc)
                continue
            meta, body = _parse_frontmatter(raw)
            if (meta.get("kind") or "").strip().lower() != "columnista":
                continue
            try:
                cid = int(meta.get("columnista_id") or "0")
            except ValueError:
                continue
            nombre = (meta.get("nombre") or "").strip()
            autor_url = (meta.get("autor_url") or "").strip()
            slug = (meta.get("slug") or "").strip()
            st = meta.get("scraped_at") or ""
            try:
                scraped_at = datetime.fromisoformat(str(st).replace("Z", "+00:00"))
            except ValueError:
                scraped_at = datetime.now(timezone.utc)
            perfil = body.strip()
            rows_col.append((cid, nombre, autor_url, slug, perfil, scraped_at, key))

    rows_op: list[tuple] = []
    prefix_op = "landing/lanacion/opinion/articulos/"
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix_op):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            if not key.endswith(".md") or date_segment not in key:
                continue
            try:
                resp = client.get_object(Bucket=bucket, Key=key)
                raw = resp["Body"].read().decode("utf-8", errors="replace")
            except (ClientError, BotoCoreError) as exc:
                context.log.warning("skip read %s: %s", key, exc)
                continue
            meta, body = _parse_frontmatter(raw)
            if (meta.get("kind") or "").strip().lower() != "opinion":
                continue
            try:
                cid = int(meta.get("columnista_id") or "0")
            except ValueError:
                continue
            titulo = (meta.get("title") or "").strip()
            url = (meta.get("url") or "").strip()
            tema = (meta.get("tema") or "").strip()
            fp = meta.get("fecha_publicacion") or ""
            try:
                fecha_pub = datetime.fromisoformat(str(fp).replace("Z", "+00:00"))
            except ValueError:
                fecha_pub = datetime(y, m, dd, tzinfo=timezone.utc)
            st = meta.get("scraped_at") or ""
            try:
                scraped_at = datetime.fromisoformat(str(st).replace("Z", "+00:00"))
            except ValueError:
                scraped_at = datetime.now(timezone.utc)
            rows_op.append((cid, titulo, url, body.strip(), fecha_pub, scraped_at, key, tema))

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

        fq_col = _fqn(catalog_alias, TABLE_COLUMNISTAS)
        fq_op = _fqn(catalog_alias, TABLE_OPINIONES)
        _ensure_columnistas(con, fq_col)
        _ensure_opiniones(con, fq_op)

        con.execute(f"DELETE FROM {fq_col}")
        if rows_col:
            con.executemany(
                f"""
                INSERT INTO {fq_col}
                (columnista_id, nombre, autor_url, slug, perfil_politico, scraped_at, landing_key)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                rows_col,
            )

        con.execute(
            f"""
            DELETE FROM {fq_op}
            WHERE CAST(fecha_publicacion AS DATE) = DATE '{context.partition_key}';
            """
        )
        if rows_op:
            con.executemany(
                f"""
                INSERT INTO {fq_op}
                (columnista_id, titulo, url, cuerpo_md, fecha_publicacion, scraped_at, landing_key, tema)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                rows_op,
            )

        n_c = con.execute(f"SELECT COUNT(*) FROM {fq_col}").fetchone()[0]
        n_o = con.execute(f"SELECT COUNT(*) FROM {fq_op}").fetchone()[0]

    return MaterializeResult(
        metadata={
            "partition": context.partition_key,
            "columnistas_rows": len(rows_col),
            "opiniones_rows_inserted": len(rows_op),
            "table_columnistas_total": int(n_c),
            "table_opiniones_total": int(n_o),
            "duckdb_path": duck_path,
            "storage": "iceberg_rest" if catalog_alias else "duckdb_native",
            "fqn_columnistas": MetadataValue.text(fq_col),
            "fqn_opiniones": MetadataValue.text(fq_op),
        }
    )
