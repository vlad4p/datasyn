"""Merge DuckDB warehouse tables with Dagster GraphQL catalog and optional Postgres catalog."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient

from agent.utils.dagster_graphql import (
    dagster_assets_by_fqn,
    dagster_graphql_url,
    fetch_dagster_asset_catalog,
    fetch_dagster_asset_detail,
)
from agent.utils.mcp_connections import load_mcp_tool_connections
from agent.utils.warehouse_schema import _extract_tool_text, warehouse_tables_payload

_MEDALLION = frozenset({"bronze", "silver", "gold"})
_FQN_RE = re.compile(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$")


def _layer_for_schema(schema: str) -> str:
    s = (schema or "").strip().lower()
    if s in _MEDALLION:
        return s
    return "other"


def _parse_entity_json(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _entity_fields(entity: dict[str, Any]) -> dict[str, Any]:
    cols = entity.get("columns")
    column_count: int | None = None
    if isinstance(cols, list):
        column_count = len(cols)
    elif isinstance(cols, dict):
        column_count = len(cols)

    def _str_list(key: str) -> list[str]:
        v = entity.get(key)
        if not v:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x]
        return [str(v)]

    dagster_job = None
    for key in ("dagster_job", "job", "source_job", "materialization_job"):
        if entity.get(key):
            dagster_job = str(entity[key])
            break

    last_updated = None
    for key in ("last_updated", "updated_at", "modified_at"):
        if entity.get(key):
            last_updated = str(entity[key])
            break

    return {
        "description": (entity.get("description") or entity.get("summary") or "") or None,
        "column_count": column_count,
        "tags": _str_list("tags"),
        "owners": _str_list("owners"),
        "lineage": _str_list("lineage"),
        "dagster_job": dagster_job,
        "last_updated": last_updated,
        "columns": cols if isinstance(cols, (list, dict)) else None,
    }


async def _invoke_catalog_query(sql: str, max_rows: int = 500) -> dict[str, Any] | None:
    """Run dagster_catalog_execute_query if the tool is bound."""
    client = MultiServerToolClient(load_mcp_tool_connections(), tool_name_prefix=True)
    tools = await client.get_tools()
    for t in tools:
        if str(getattr(t, "name", "") or "").strip() != "dagster_catalog_execute_query":
            continue
        raw = await t.ainvoke({"sql": sql, "max_rows": max_rows})
        text = _extract_tool_text(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
    return None


async def fetch_postgres_catalog_entities() -> tuple[dict[str, dict[str, Any]], str]:
    """Return map fqn -> parsed entity fields; catalog_status."""
    result = await _invoke_catalog_query(
        "SELECT fully_qualified_name, entity_json FROM dataset_entity "
        "ORDER BY fully_qualified_name LIMIT 500"
    )
    if result is None:
        return {}, "unavailable"
    if "raw" in result and "rows" not in result:
        return {}, "error"
    rows = result.get("rows") or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        fqn = str(row.get("fully_qualified_name") or "").strip()
        if not fqn:
            continue
        entity = _parse_entity_json(row.get("entity_json"))
        out[fqn] = _entity_fields(entity)
    return out, "ok"


def _warehouse_rows(warehouse: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    layers = warehouse.get("layers") or {}
    for schema in ("bronze", "silver", "gold"):
        for t in layers.get(schema) or []:
            rows.append(
                {
                    "schema": schema,
                    "name": t.get("name", ""),
                    "table_type": t.get("table_type", ""),
                }
            )
    for t in warehouse.get("other") or []:
        rows.append(
            {
                "schema": t.get("schema", ""),
                "name": t.get("name", ""),
                "table_type": t.get("table_type", ""),
            }
        )
    return rows


def _list_warehouse_fqns(warehouse: dict[str, Any]) -> list[str]:
    fqns: list[str] = []
    for row in _warehouse_rows(warehouse):
        schema = (row.get("schema") or "").strip()
        name = (row.get("name") or "").strip()
        if name:
            fqns.append(f"{schema}.{name}" if schema else name)
    return sorted(set(fqns))


def _apply_dagster_meta(card: dict[str, Any], dagster: dict[str, Any]) -> None:
    card["in_dagster"] = True
    card["dagster_asset_key"] = dagster.get("dagster_asset_key")
    card["dagster_asset_path"] = dagster.get("dagster_asset_path")
    card["lineage_upstream"] = dagster.get("lineage_upstream") or []
    card["lineage_downstream"] = dagster.get("lineage_downstream") or []
    if dagster.get("description") and not card.get("description"):
        card["description"] = dagster["description"]
    if dagster.get("job_names"):
        card["dagster_jobs"] = dagster["job_names"]
    if dagster.get("group_name"):
        card["dagster_group"] = dagster["group_name"]
    if dagster.get("compute_kind"):
        card["dagster_compute_kind"] = dagster["compute_kind"]
    if dagster.get("kinds"):
        card["dagster_kinds"] = dagster["kinds"]
    if dagster.get("owners"):
        card["dagster_owners"] = dagster["owners"]
    if dagster.get("is_partitioned") is not None:
        card["dagster_is_partitioned"] = dagster["is_partitioned"]
    if dagster.get("latest_materialization"):
        card["dagster_latest_materialization"] = dagster["latest_materialization"]
    if dagster.get("definition_metadata"):
        card["dagster_definition_metadata"] = dagster["definition_metadata"]
    if dagster.get("duckdb_fqn") and not card.get("fqn", "").startswith("dagster/"):
        card["dagster_table_fqn"] = dagster["duckdb_fqn"]
    extra_tags = dagster.get("tags") or []
    if extra_tags:
        existing = set(card.get("tags") or [])
        card["tags"] = sorted(existing | set(extra_tags))


def merge_dataset_cards(
    warehouse: dict[str, Any],
    postgres_catalog: dict[str, dict[str, Any]],
    dagster_by_fqn: dict[str, dict[str, Any]],
    dagster_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build unified dataset card list."""
    cards: dict[str, dict[str, Any]] = {}

    for row in _warehouse_rows(warehouse):
        schema = (row.get("schema") or "").strip()
        name = (row.get("name") or "").strip()
        if not name:
            continue
        fqn = f"{schema}.{name}" if schema else name
        cards[fqn] = {
            "fqn": fqn,
            "schema": schema,
            "name": name,
            "layer": _layer_for_schema(schema),
            "table_type": row.get("table_type") or None,
            "in_warehouse": True,
            "in_catalog": False,
            "in_dagster": False,
            "lineage_upstream": [],
            "lineage_downstream": [],
        }

    for fqn, meta in postgres_catalog.items():
        parts = fqn.split(".", 1)
        schema = parts[0] if len(parts) == 2 else ""
        name = parts[1] if len(parts) == 2 else fqn
        if fqn in cards:
            card = cards[fqn]
            card["in_catalog"] = True
        else:
            card = {
                "fqn": fqn,
                "schema": schema,
                "name": name,
                "layer": _layer_for_schema(schema),
                "table_type": None,
                "in_warehouse": False,
                "in_catalog": True,
                "in_dagster": False,
                "lineage_upstream": [],
                "lineage_downstream": [],
            }
            cards[fqn] = card
        card.update({k: v for k, v in meta.items() if k != "columns" and v is not None})

    for fqn, dagster in dagster_by_fqn.items():
        parts = fqn.split(".", 1)
        schema = parts[0] if len(parts) == 2 else ""
        name = parts[1] if len(parts) == 2 else fqn
        if fqn in cards:
            _apply_dagster_meta(cards[fqn], dagster)
        else:
            card = {
                "fqn": fqn,
                "schema": schema,
                "name": name,
                "layer": _layer_for_schema(schema),
                "table_type": None,
                "in_warehouse": False,
                "in_catalog": False,
                "in_dagster": True,
                "lineage_upstream": [],
                "lineage_downstream": [],
            }
            _apply_dagster_meta(card, dagster)
            cards[fqn] = card

    # Dagster assets without inferred DuckDB FQN — show under synthetic key
    for asset in dagster_assets:
        if asset.get("duckdb_fqn"):
            continue
        key = asset.get("dagster_asset_key") or ""
        if not key:
            continue
        pseudo = f"dagster/{key}"
        if pseudo in cards:
            continue
        card = {
            "fqn": pseudo,
            "schema": "",
            "name": key.split("/")[-1] if "/" in key else key,
            "layer": "other",
            "table_type": None,
            "in_warehouse": False,
            "in_catalog": False,
            "in_dagster": True,
            "lineage_upstream": asset.get("lineage_upstream") or [],
            "lineage_downstream": asset.get("lineage_downstream") or [],
            "dagster_asset_key": key,
            "description": asset.get("description"),
            "dagster_only": True,
        }
        if asset.get("job_names"):
            card["dagster_jobs"] = asset["job_names"]
        if asset.get("group_name"):
            card["dagster_group"] = asset["group_name"]
        if asset.get("latest_materialization"):
            card["dagster_latest_materialization"] = asset["latest_materialization"]
        if asset.get("duckdb_fqn"):
            card["dagster_table_fqn"] = asset["duckdb_fqn"]
        cards[pseudo] = card

    result = list(cards.values())
    result.sort(key=lambda c: (c.get("layer", ""), c.get("fqn", "")))
    return result


async def catalog_datasets_payload(*, duckdb_table: str | None = None) -> dict[str, Any]:
    """Response for GET /catalog/datasets."""
    warehouse = await warehouse_tables_payload()
    postgres_map, catalog_status = await fetch_postgres_catalog_entities()
    dagster_assets, dagster_status, dagster_error = await fetch_dagster_asset_catalog()
    dagster_by_fqn = dagster_assets_by_fqn(dagster_assets)

    datasets = merge_dataset_cards(warehouse, postgres_map, dagster_by_fqn, dagster_assets)

    if duckdb_table:
        needle = duckdb_table.strip().lower()
        datasets = [d for d in datasets if (d.get("fqn") or "").lower() == needle]

    return {
        "status": "ok",
        "catalog_status": catalog_status,
        "dagster_status": dagster_status,
        "dagster_error": dagster_error,
        "dagster_graphql_url": None,  # filled in main if needed
        "warehouse_tables": _list_warehouse_fqns(warehouse),
        "datasets": datasets,
        "count": len(datasets),
    }


async def _invoke_duckdb_query(sql: str) -> list[dict[str, Any]]:
    client = MultiServerToolClient(load_mcp_tool_connections(), tool_name_prefix=True)
    tools = await client.get_tools()
    for t in tools:
        if str(getattr(t, "name", "") or "").strip() != "duckdb_execute_query":
            continue
        raw = await t.ainvoke({"sql": sql})
        text = _extract_tool_text(raw)
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "rows" in data:
                return data["rows"]
        except json.JSONDecodeError:
            pass
        return [{"raw": text[:2000]}]
    return []


async def catalog_dataset_detail_payload(fqn: str) -> dict[str, Any]:
    """Response for GET /catalog/datasets/{fqn}."""
    fqn = fqn.strip()
    if not fqn or (not fqn.startswith("dagster/") and not _FQN_RE.match(fqn)):
        return {"status": "error", "error": "Invalid FQN (expected schema.table)"}

    list_payload = await catalog_datasets_payload()
    card = next((d for d in list_payload["datasets"] if d["fqn"] == fqn), None)

    catalog_cols: list[dict[str, str]] = []
    postgres_map, _ = await fetch_postgres_catalog_entities()
    if fqn in postgres_map:
        cols = postgres_map[fqn].get("columns")
        if isinstance(cols, list):
            for c in cols:
                if isinstance(c, dict):
                    catalog_cols.append(
                        {
                            "name": str(c.get("name") or c.get("column") or ""),
                            "type": str(c.get("type") or c.get("data_type") or ""),
                            "description": str(c.get("description") or ""),
                        }
                    )

    dagster_detail: dict[str, Any] | None = None
    if card and card.get("dagster_asset_path"):
        dagster_detail = await fetch_dagster_asset_detail(card["dagster_asset_path"])
    elif card and card.get("dagster_asset_key"):
        dagster_detail = await fetch_dagster_asset_detail(
            str(card["dagster_asset_key"]).split("/")
        )

    wh_cols: list[dict[str, str]] = []
    if _FQN_RE.match(fqn):
        parts = fqn.split(".", 1)
        schema, table = parts[0], parts[1]
        try:
            esc_schema = schema.replace("'", "''")
            esc_table = table.replace("'", "''")
            sql = (
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_schema = '{esc_schema}' AND table_name = '{esc_table}' "
                f"ORDER BY ordinal_position LIMIT 200"
            )
            rows = await _invoke_duckdb_query(sql)
            for r in rows:
                if isinstance(r, dict) and r.get("column_name"):
                    wh_cols.append(
                        {
                            "name": str(r["column_name"]),
                            "type": str(r.get("data_type") or ""),
                            "description": "",
                        }
                    )
        except Exception as exc:
            wh_cols = [{"error": str(exc)[:200]}]

    lineage = {
        "upstream": (dagster_detail or card or {}).get("lineage_upstream") or [],
        "downstream": (dagster_detail or card or {}).get("lineage_downstream") or [],
    }

    return {
        "status": "ok",
        "dataset": card,
        "catalog_columns": catalog_cols,
        "warehouse_columns": wh_cols,
        "dagster": dagster_detail,
        "dagster_graphql_url": dagster_graphql_url(),
        "lineage": lineage,
    }
