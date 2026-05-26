"""OECD AIM Argentina incidents: scrape → MinIO JSON landing → ``bronze.oecd_ai_incidents``.

Particiones diarias: cada partición corresponde a la fecha del incidente AIM
que se consulta en OECD AI para Argentina.
"""

import json
import os
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

from datasyn.assets.bronze.oecd_ai_incidents.lib import (
    DEFAULT_COUNTRY,
    build_search_url,
    scrape_incidents_for_partition,
)
from datasyn.utils.iceberg import attach_iceberg_catalog, iceberg_publish_configured
from datasyn.utils.minio_client import boto3_minio_s3_client

BRONZE_SCHEMA = "bronze"
TABLE_NAME = "oecd_ai_incidents"
LANDING_PREFIX = "landing/oecd_ai_incidents"

OECD_AI_INCIDENTS_DAILY = DailyPartitionsDefinition(
    start_date=datetime(1900, 1, 1),
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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _table_fqn(catalog_alias: str | None) -> str:
    if catalog_alias:
        return f"{catalog_alias}.{BRONZE_SCHEMA}.{TABLE_NAME}"
    return f"{BRONZE_SCHEMA}.{TABLE_NAME}"


def _ensure_table(con: Any, fqn: str) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {fqn} (
            partition_date DATE,
            incident_date DATE,
            incident_id VARCHAR,
            title VARCHAR,
            url VARCHAR,
            countries VARCHAR,
            summary VARCHAR,
            monitor_reason VARCHAR,
            severity VARCHAR,
            article_count INTEGER,
            ai_principles_json VARCHAR,
            industries_json VARCHAR,
            affected_stakeholders_json VARCHAR,
            harm_types_json VARCHAR,
            business_functions_json VARCHAR,
            ai_system_tasks_json VARCHAR,
            autonomy_level VARCHAR,
            languages_json VARCHAR,
            concepts_json VARCHAR,
            related_articles_json VARCHAR,
            raw_json VARCHAR,
            scraped_at TIMESTAMP,
            landing_key VARCHAR
        );
        """
    )


@asset(
    partitions_def=OECD_AI_INCIDENTS_DAILY,
    group_name="bronze",
    compute_kind="python",
    description=(
        "Scrape OECD AIM incidents for Argentina on the partition date and stores one JSON "
        f"per incident plus a manifest under ``{LANDING_PREFIX}/YYYY/MM/DD/`` in MinIO."
    ),
)
def oecd_ai_incidents_landing(context: AssetExecutionContext) -> MaterializeResult:
    day = _partition_date(context)
    scraped_at = datetime.now(timezone.utc)
    context.log.info("OECD AI incidents scrape partition=%s country=%s", context.partition_key, DEFAULT_COUNTRY)
    docs = scrape_incidents_for_partition(partition_day=day, scraped_at=scraped_at)

    client = _s3()
    bucket = _bucket()
    prefix = _landing_dir_for_partition(day)
    keys: list[str] = []
    manifest: list[dict[str, Any]] = []
    article_count = 0

    for doc in docs:
        body = _json_dumps(doc.payload).encode("utf-8")
        try:
            client.put_object(
                Bucket=bucket,
                Key=doc.landing_key,
                Body=body,
                ContentType="application/json; charset=utf-8",
            )
        except (ClientError, BotoCoreError) as exc:
            raise Failure(f"MinIO put failed s3://{bucket}/{doc.landing_key}: {exc}") from exc
        keys.append(doc.landing_key)
        related = _as_list(doc.payload.get("related_articles"))
        article_count += len(related)
        manifest.append(
            {
                "incident_id": doc.incident_id,
                "title": doc.title,
                "url": doc.url,
                "incident_date": doc.incident_date.isoformat() if doc.incident_date else None,
                "landing_key": doc.landing_key,
                "related_articles": [
                    {"name": a.get("name") or a.get("title"), "url": a.get("url")}
                    for a in related
                    if isinstance(a, dict)
                ],
            }
        )

    manifest_key = f"{prefix}/manifest.json"
    try:
        client.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=_json_dumps(manifest).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
    except (ClientError, BotoCoreError) as exc:
        raise Failure(f"MinIO manifest put failed s3://{bucket}/{manifest_key}: {exc}") from exc

    return MaterializeResult(
        metadata={
            "partition": context.partition_key,
            "country": DEFAULT_COUNTRY,
            "search_url": MetadataValue.url(build_search_url(day)),
            "incidents_written": len(docs),
            "related_articles": article_count,
            "minio_bucket": bucket,
            "manifest_key": manifest_key,
            "sample_keys": MetadataValue.json(keys[:20]),
        }
    )


@asset(
    deps=[oecd_ai_incidents_landing],
    partitions_def=OECD_AI_INCIDENTS_DAILY,
    group_name="bronze",
    compute_kind="duckdb",
    description=(
        f"Reads OECD AIM JSON landing objects for the partition and replaces that day in "
        f"``{BRONZE_SCHEMA}.{TABLE_NAME}`` (Iceberg REST if configured)."
    ),
)
def oecd_ai_incidents_bronze(
    context: AssetExecutionContext, database: DuckDBResource
) -> MaterializeResult:
    day = _partition_date(context)
    manifest_key = f"{_landing_dir_for_partition(day)}/manifest.json"

    client = _s3()
    bucket = _bucket()
    try:
        resp = client.get_object(Bucket=bucket, Key=manifest_key)
        manifest = json.loads(resp["Body"].read().decode("utf-8"))
    except (ClientError, BotoCoreError) as exc:
        raise Failure(f"No manifest at s3://{bucket}/{manifest_key}: {exc}") from exc

    rows: list[tuple[Any, ...]] = []
    for item in manifest if isinstance(manifest, list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("landing_key") or "")
        if not key:
            continue
        try:
            obj = client.get_object(Bucket=bucket, Key=key)
            payload = json.loads(obj["Body"].read().decode("utf-8"))
        except (ClientError, BotoCoreError, json.JSONDecodeError) as exc:
            context.log.warning("skip OECD landing object s3://%s/%s: %s", bucket, key, exc)
            continue
        if not isinstance(payload, dict):
            continue

        properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
        countries = ", ".join(str(v) for v in _as_list(payload.get("location")) if v)
        severity = ", ".join(str(v) for v in _as_list(payload.get("severity")) if v)
        incident_date = _parse_date(payload.get("incident_date")) or day

        rows.append(
            (
                day,
                incident_date,
                _as_text(payload.get("incident_id")),
                _as_text(payload.get("title")),
                _as_text(payload.get("url")),
                countries,
                _as_text(payload.get("summary")),
                _as_text(payload.get("monitor_reason")),
                severity,
                int(payload.get("article_count") or len(_as_list(payload.get("related_articles")))),
                _json_dumps(payload.get("ai_principles") or properties.get("principles") or []),
                _json_dumps(payload.get("industries") or properties.get("industries") or []),
                _json_dumps(
                    payload.get("affected_stakeholders") or properties.get("harmed_entities") or []
                ),
                _json_dumps(payload.get("harm_types") or properties.get("harm_types") or []),
                _json_dumps(
                    payload.get("business_functions") or properties.get("business_functions") or []
                ),
                _json_dumps(payload.get("ai_system_tasks") or properties.get("ai_tasks") or []),
                _as_text(payload.get("autonomy_level") or properties.get("autonomy_level")),
                _json_dumps(payload.get("languages") or properties.get("languages") or []),
                _json_dumps(payload.get("concepts") or []),
                _json_dumps(payload.get("related_articles") or []),
                _json_dumps(payload),
                _parse_datetime(payload.get("scraped_at")),
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
            WHERE partition_date = DATE '{context.partition_key}';
            """
        )
        if rows:
            con.executemany(
                f"""
                INSERT INTO {fqn}
                (partition_date, incident_date, incident_id, title, url, countries, summary,
                 monitor_reason, severity, article_count, ai_principles_json, industries_json,
                 affected_stakeholders_json, harm_types_json, business_functions_json,
                 ai_system_tasks_json, autonomy_level, languages_json, concepts_json,
                 related_articles_json, raw_json, scraped_at, landing_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
