"""Data catalog MCP (FastMCP HTTP). Stores OpenMetadata-inspired dataset/table metadata in MongoDB."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from bson.json_util import dumps as bson_dumps
from dotenv import load_dotenv
from fastmcp import FastMCP
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.is_file():
    load_dotenv(_env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [catalog-mcp] %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("catalog-mcp")

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "datacyber_catalog")
COLLECTION = "datasets"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8041"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")
LIST_CAP = max(1, min(int(os.environ.get("CATALOG_LIST_CAP", "100")), 500))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_mongo: MongoClient | None = None


def _client() -> MongoClient:
    global _mongo
    if _mongo is None:
        _mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    return _mongo


def _collection():
    return _client()[MONGO_DB][COLLECTION]


mcp = FastMCP(
    name="catalog-mcp",
    instructions=(
        "Datacyber data catalog (MongoDB), modeled after OpenMetadata table/service concepts: "
        "fullyQualifiedName (FQN), service, database, schema, columns (name, dataType, description, tags), "
        "owners, tags, glossaryTerms, upstreamLineage / downstreamLineage entity references. "
        "Use after creating or changing warehouse tables to register metadata, document columns, and record lineage. "
        "FQN is unique (e.g. duckdb-warehouse.main.public.my_table). "
        "Tools: list_datasets, get_dataset, search_datasets, register_or_update_dataset, set_lineage."
    ),
)


def _parse_json(name: str, raw: str, default: Any) -> tuple[Any, str | None]:
    text = (raw or "").strip()
    if not text:
        return default, None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return default, f"Error: invalid JSON in {name}: {exc}"


def _serialize_doc(doc: dict[str, Any]) -> str:
    if doc is None:
        return "{}"
    out = dict(doc)
    if "_id" in out and isinstance(out["_id"], ObjectId):
        out["_id"] = str(out["_id"])
    return bson_dumps(out, indent=2)


def _dataset_summary_for_listing(doc: dict[str, Any]) -> dict[str, Any]:
    """UI / list_datasets / HTTP listing — same shape everywhere."""
    cols = doc.get("columns")
    col_count = len(cols) if isinstance(cols, list) else 0
    desc = doc.get("description")
    if isinstance(desc, str) and len(desc) > 400:
        desc = desc[:397] + "…"
    oid = doc.get("_id")
    return {
        "id": str(oid) if isinstance(oid, ObjectId) else str(oid) if oid is not None else None,
        "fullyQualifiedName": doc.get("fullyQualifiedName"),
        "name": doc.get("name"),
        "displayName": doc.get("displayName"),
        "description": desc or "",
        "tableType": doc.get("tableType"),
        "service": doc.get("service"),
        "database": doc.get("database"),
        "schema": doc.get("schema"),
        "columnCount": col_count,
        "tagCount": len(doc["tags"]) if isinstance(doc.get("tags"), list) else 0,
        "updatedAt": doc.get("updatedAt"),
        "createdAt": doc.get("createdAt"),
    }


@mcp.tool()
def list_datasets(
    service_name: str = "",
    database_name: str = "",
    schema_name: str = "",
    limit: int = 50,
) -> str:
    """List cataloged datasets with optional filters (OpenMetadata service → database → schema → table hierarchy).

    Args:
        service_name: Filter by ``service.name`` (partial match, case-insensitive).
        database_name: Filter by ``database.name``.
        schema_name: Filter by ``schema.name``.
        limit: Max documents (capped by server).

    Returns:
        JSON array of summary objects (FQN, names, service/schema, tableType, description snippet,
        columnCount, tagCount, timestamps) for UI and agents.
    """
    lim = max(1, min(int(limit or 50), LIST_CAP))
    q: dict[str, Any] = {}
    if service_name.strip():
        q["service.name"] = {"$regex": service_name.strip(), "$options": "i"}
    if database_name.strip():
        q["database.name"] = database_name.strip()
    if schema_name.strip():
        q["schema.name"] = schema_name.strip()

    t0 = time.perf_counter()
    col = _collection()
    cur = col.find(q).sort("updatedAt", -1).limit(lim)
    rows = [_dataset_summary_for_listing(doc) for doc in cur]
    log.info("list_datasets count=%s ms=%.2f", len(rows), (time.perf_counter() - t0) * 1000)
    return json.dumps(rows, indent=2, default=str)


@mcp.tool()
def get_dataset(fqn: str) -> str:
    """Fetch one dataset by fullyQualifiedName (exact match). Returns full document including columns and lineage."""
    key = (fqn or "").strip()
    if not key:
        return "Error: fqn is required"
    t0 = time.perf_counter()
    doc = _collection().find_one({"fullyQualifiedName": key})
    log.info("get_dataset hit=%s ms=%.2f", doc is not None, (time.perf_counter() - t0) * 1000)
    if not doc:
        return f"Error: no dataset with fullyQualifiedName={key!r}"
    return _serialize_doc(doc)


@mcp.tool()
def search_datasets(query: str, limit: int = 20) -> str:
    """Full-text search on name, displayName, description, fullyQualifiedName (MongoDB text index)."""
    q = (query or "").strip()
    if not q:
        return "Error: query is required"
    lim = max(1, min(int(limit or 20), LIST_CAP))
    t0 = time.perf_counter()
    try:
        cur = _collection().find({"$text": {"$search": q}}).limit(lim)
        rows = list(cur)
    except Exception as exc:
        log.exception("search_datasets")
        return f"Error: {type(exc).__name__}: {exc}"
    log.info("search_datasets n=%s ms=%.2f", len(rows), (time.perf_counter() - t0) * 1000)
    return json.dumps(
        [
            {
                "fullyQualifiedName": d.get("fullyQualifiedName"),
                "name": d.get("name"),
                "displayName": d.get("displayName"),
                "description": (d.get("description") or "")[:500],
                "score": d.get("score"),
            }
            for d in rows
        ],
        indent=2,
        default=str,
    )


@mcp.tool()
def register_or_update_dataset(
    fully_qualified_name: str,
    name: str,
    service_name: str,
    database_name: str,
    schema_name: str,
    display_name: str = "",
    description: str = "",
    service_type: str = "DatabaseService",
    table_type: str = "Regular",
    columns_json: str = "[]",
    tags_json: str = "[]",
    owners_json: str = "[]",
    glossary_terms_json: str = "[]",
    source_url: str = "",
    custom_properties_json: str = "{}",
) -> str:
    """Create or replace catalog metadata for a table/view (OpenMetadata-style entity).

    Args:
        fully_qualified_name: Unique FQN, e.g. ``duckdb-warehouse.main.public.sales``.
        name: Entity name (last segment).
        service_name: Database service name (connector / service in OM).
        database_name: Database name.
        schema_name: Schema name.
        display_name: Optional display name.
        description: Free-text description.
        service_type: Default ``DatabaseService`` (OM EntityReference type).
        table_type: ``Regular``, ``View``, ``MaterializedView``, ``External``, etc.
        columns_json: JSON array of columns: ``[{"name","dataType","description","ordinalPosition","tags","dataLength","constraint"}]``.
        tags_json: JSON array: ``[{"tagFQN","source","labelType","state"}]`` (OM TagLabel).
        owners_json: JSON array: ``[{"name","type","id"}]`` (OM EntityReference).
        glossary_terms_json: JSON array of term references.
        source_url: Optional link to external docs or source.
        custom_properties_json: JSON object for arbitrary key/value metadata.

    Returns:
        JSON of the stored document (or error string).
    """
    fqn = (fully_qualified_name or "").strip()
    if not fqn:
        return "Error: fully_qualified_name is required"
    nm = (name or "").strip()
    if not nm:
        return "Error: name is required"
    sn = (service_name or "").strip()
    dbn = (database_name or "").strip()
    scn = (schema_name or "").strip()
    if not (sn and dbn and scn):
        return "Error: service_name, database_name, and schema_name are required"

    columns, err = _parse_json("columns_json", columns_json, [])
    if err:
        return err
    if not isinstance(columns, list):
        return "Error: columns_json must be a JSON array"

    tags, err = _parse_json("tags_json", tags_json, [])
    if err:
        return err
    if not isinstance(tags, list):
        return "Error: tags_json must be a JSON array"

    owners, err = _parse_json("owners_json", owners_json, [])
    if err:
        return err
    if not isinstance(owners, list):
        return "Error: owners_json must be a JSON array"

    glossary_terms, err = _parse_json("glossary_terms_json", glossary_terms_json, [])
    if err:
        return err
    if not isinstance(glossary_terms, list):
        return "Error: glossary_terms_json must be a JSON array"

    custom_properties, err = _parse_json("custom_properties_json", custom_properties_json, {})
    if err:
        return err
    if not isinstance(custom_properties, dict):
        return "Error: custom_properties_json must be a JSON object"

    now = _utc_now()
    doc: dict[str, Any] = {
        "fullyQualifiedName": fqn,
        "name": nm,
        "displayName": (display_name or "").strip() or nm,
        "description": (description or "").strip(),
        "tableType": (table_type or "Regular").strip(),
        "service": {"name": sn, "type": (service_type or "DatabaseService").strip()},
        "database": {"name": dbn},
        "schema": {"name": scn},
        "columns": columns,
        "tags": tags,
        "owners": owners,
        "glossaryTerms": glossary_terms,
        "upstreamLineage": [],
        "downstreamLineage": [],
        "sourceUrl": (source_url or "").strip() or None,
        "customProperties": custom_properties,
        "updatedAt": now,
    }
    # Preserve lineage if updating
    col = _collection()
    existing = col.find_one({"fullyQualifiedName": fqn}, projection={"upstreamLineage": 1, "downstreamLineage": 1, "createdAt": 1})
    if existing:
        doc["upstreamLineage"] = existing.get("upstreamLineage") or []
        doc["downstreamLineage"] = existing.get("downstreamLineage") or []
        doc["createdAt"] = existing.get("createdAt") or now
    else:
        doc["createdAt"] = now

    try:
        col.replace_one({"fullyQualifiedName": fqn}, doc, upsert=True)
    except DuplicateKeyError as exc:
        return f"Error: duplicate key: {exc}"
    out = col.find_one({"fullyQualifiedName": fqn})
    log.info("register_or_update_dataset fqn=%s", fqn)
    return _serialize_doc(out) if out else "{}"


def _norm_lineage_list(raw: list[Any], direction: str) -> list[dict[str, Any]]:
    """Accept list of strings (FQN) or OM-style dicts with fullyQualifiedName."""
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(
                {
                    "type": "table",
                    "fullyQualifiedName": item.strip(),
                    "description": None,
                    "direction": direction,
                }
            )
        elif isinstance(item, dict):
            ref = item.get("fullyQualifiedName") or item.get("fqn")
            if isinstance(ref, str) and ref.strip():
                row = {
                    "type": str(item.get("type") or "table"),
                    "fullyQualifiedName": ref.strip(),
                    "description": item.get("description"),
                    "direction": direction,
                }
                if "id" in item:
                    row["id"] = item["id"]
                out.append(row)
    return out


@mcp.tool()
def set_lineage(
    dataset_fqn: str,
    upstream_fqns_json: str = "[]",
    downstream_fqns_json: str = "[]",
) -> str:
    """Set upstream and downstream lineage for a dataset (OpenMetadata entity lineages as FQN lists).

    Each JSON array may contain plain FQN strings or objects with ``fullyQualifiedName`` / ``type`` / ``description``.
    This replaces existing upstreamLineage / downstreamLineage on the document.
    """
    fqn = (dataset_fqn or "").strip()
    if not fqn:
        return "Error: dataset_fqn is required"

    up_raw, err = _parse_json("upstream_fqns_json", upstream_fqns_json, [])
    if err:
        return err
    down_raw, err = _parse_json("downstream_fqns_json", downstream_fqns_json, [])
    if err:
        return err
    if not isinstance(up_raw, list) or not isinstance(down_raw, list):
        return "Error: lineage JSON must be arrays"

    col = _collection()
    existing = col.find_one({"fullyQualifiedName": fqn})
    if not existing:
        return f"Error: dataset not found: {fqn!r}"

    update = {
        "$set": {
            "upstreamLineage": _norm_lineage_list(up_raw, "upstream"),
            "downstreamLineage": _norm_lineage_list(down_raw, "downstream"),
            "updatedAt": _utc_now(),
        }
    }
    col.update_one({"fullyQualifiedName": fqn}, update)
    doc = col.find_one({"fullyQualifiedName": fqn})
    log.info("set_lineage fqn=%s", fqn)
    return _serialize_doc(doc) if doc else "{}"


@mcp.custom_route("/api/datasets", methods=["GET"])
async def http_list_datasets(request: Request) -> Response:
    """JSON list for the UI / brain proxy (summary rows, no full column payloads)."""
    try:
        lim = int(request.query_params.get("limit", 48))
    except ValueError:
        lim = 48
    lim = max(1, min(lim, LIST_CAP))
    service_name = (request.query_params.get("service_name") or "").strip()
    database_name = (request.query_params.get("database_name") or "").strip()
    schema_name = (request.query_params.get("schema_name") or "").strip()

    q: dict[str, Any] = {}
    if service_name:
        q["service.name"] = {"$regex": service_name, "$options": "i"}
    if database_name:
        q["database.name"] = database_name
    if schema_name:
        q["schema.name"] = schema_name

    t0 = time.perf_counter()
    col = _collection()
    cur = col.find(q).sort("updatedAt", -1).limit(lim)
    rows = [_dataset_summary_for_listing(doc) for doc in cur]
    log.info("http_list_datasets n=%s ms=%.2f", len(rows), (time.perf_counter() - t0) * 1000)
    body = json.dumps({"ok": True, "count": len(rows), "datasets": rows}, default=str)
    return Response(content=body, media_type="application/json")


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    try:
        _client().admin.command("ping")
        return PlainTextResponse("ok")
    except Exception as exc:
        return PlainTextResponse(f"error: {exc}", status_code=503)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path=MCP_HTTP_PATH,
    )
