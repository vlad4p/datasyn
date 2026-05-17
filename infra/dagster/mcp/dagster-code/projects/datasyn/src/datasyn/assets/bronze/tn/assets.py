"""TN: scrape → MinIO landing (markdown) → ``bronze.tn_noticias`` (Iceberg si aplica).

Particiones diarias: cada partición corresponde a un día calendario; se enlazan notas
por fecha en la URL del artículo. Job ``tn_backfill_job`` materializa
``tn_landing_markdown`` y luego ``tn_noticias_bronze`` para el rango elegido en el Launchpad.

Fuentes: https://tn.com.ar/tecno/ , /politica/ , /economia/ , /opinion/
"""

import os
from datetime import date, datetime, timezone

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

from datasyn.assets.bronze.tn.lib import (
    SECTIONS,
    build_markdown_file,
    scrape_articles_for_partition,
)
from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured
from datasyn.utils.minio_client import boto3_minio_s3_client

BRONZE_SCHEMA = "bronze"
TABLE_NAME = "tn_noticias"

TN_DAILY = DailyPartitionsDefinition(
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


def _table_fqn(catalog_alias: str | None) -> str:
    if catalog_alias:
        return f"{catalog_alias}.{BRONZE_SCHEMA}.{TABLE_NAME}"
    return f"{BRONZE_SCHEMA}.{TABLE_NAME}"


def _ensure_table(con, fqn: str) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {fqn} (
            tema VARCHAR,
            titulo VARCHAR,
            url VARCHAR,
            cuerpo_md VARCHAR,
            fecha_publicacion TIMESTAMP,
            scraped_at TIMESTAMP,
            landing_key VARCHAR
        );
        """
    )


@asset(
    partitions_def=TN_DAILY,
    group_name="bronze",
    compute_kind="python",
    description=(
        "Scrape TN (tecno, política, economía, opinión) para la fecha de partición; "
        "sube markdown a ``landing/tn/<tema>/YYYY/MM/DD/*.md`` en MinIO."
    ),
)
def tn_landing_markdown(context: AssetExecutionContext) -> MaterializeResult:
    day = _partition_date(context)
    context.log.info("tn scrape partition=%s", context.partition_key)
    docs = scrape_articles_for_partition(partition_day=day)
    client = _s3()
    bucket = _bucket()
    scraped_at = datetime.now(timezone.utc)
    n = 0
    keys: list[str] = []
    for d in docs:
        body = build_markdown_file(d, scraped_at)
        try:
            client.put_object(
                Bucket=bucket,
                Key=d.landing_key,
                Body=body.encode("utf-8"),
                ContentType="text/markdown; charset=utf-8",
            )
            keys.append(d.landing_key)
            n += 1
        except (ClientError, BotoCoreError) as exc:
            context.log.error("put_object failed %s: %s", d.landing_key, exc)
            raise Failure(f"MinIO put failed: {exc}") from exc
    return MaterializeResult(
        metadata={
            "partition": context.partition_key,
            "articles_written": n,
            "minio_bucket": bucket,
            "sample_keys": MetadataValue.json(keys[:20]),
            "secciones": MetadataValue.json(list(SECTIONS.keys())),
        }
    )


@asset(
    deps=[tn_landing_markdown],
    partitions_def=TN_DAILY,
    group_name="bronze",
    compute_kind="duckdb",
    description=(
        "Lee objetos ``landing/tn/*/YYYY/MM/DD/*.md`` de MinIO para la partición, "
        f"reemplaza filas de ese día en ``{BRONZE_SCHEMA}.{TABLE_NAME}`` e inserta (Iceberg REST si está configurado)."
    ),
)
def tn_noticias_bronze(context: AssetExecutionContext, database: DuckDBResource) -> MaterializeResult:
    day = _partition_date(context)
    y, m, dd = day.year, day.month, day.day
    prefix = "landing/tn/"
    date_segment = f"/{y:04d}/{m:02d}/{dd:02d}/"
    client = _s3()
    bucket = _bucket()
    paginator = client.get_paginator("list_objects_v2")
    rows: list[tuple] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
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
            tema = (meta.get("tema") or "").strip()
            titulo = (meta.get("title") or "").strip()
            url = (meta.get("url") or "").strip()
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
            rows.append(
                (
                    tema,
                    titulo,
                    url,
                    body,
                    fecha_pub,
                    scraped_at,
                    key,
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
            WHERE CAST(fecha_publicacion AS DATE) = DATE '{context.partition_key}';
            """
        )
        if rows:
            con.executemany(
                f"""
                INSERT INTO {fqn}
                (tema, titulo, url, cuerpo_md, fecha_publicacion, scraped_at, landing_key)
                VALUES (?, ?, ?, ?, ?, ?, ?);
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
            "storage": "iceberg_rest" if catalog_alias else "duckdb_native",
            "fqn": MetadataValue.text(fqn),
        }
    )


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    lines = raw.splitlines()
    meta: dict[str, str] = {}
    if not lines or lines[0].strip() != "---":
        return meta, raw
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
        i += 1
    body = "\n".join(lines[i + 1 :]).strip()
    return meta, body
