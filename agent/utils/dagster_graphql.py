"""Dagster GraphQL catalog client (webserver ``/graphql``).

See https://docs.dagster.io/api/graphql

Set ``DAGSTER_URL`` in repo ``.env`` to the webserver host + port only (e.g.
``http://127.0.0.1:3001`` or ``http://registry-host:3001``). The GraphQL path is appended in code.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent.config import dagster_graphql_url, settings

logger = logging.getLogger(__name__)

_METADATA_ENTRY_FRAGMENTS = """
      label
      __typename
      ... on TextMetadataEntry { text }
      ... on UrlMetadataEntry { url }
      ... on PathMetadataEntry { path }
      ... on JsonMetadataEntry { jsonString }
      ... on FloatMetadataEntry { floatValue }
      ... on IntMetadataEntry { intValue }
      ... on BoolMetadataEntry { boolValue }
      ... on MarkdownMetadataEntry { mdStr }
"""

_ASSET_NODE_FIELDS = f"""
    id
    groupName
    description
    computeKind
    kinds
    isMaterializable
    isPartitioned
    opName
    assetKey {{
      path
    }}
    tags {{
      key
      value
    }}
    owners {{
      __typename
      ... on UserAssetOwner {{ email }}
      ... on TeamAssetOwner {{ team }}
    }}
    dependencyKeys {{
      path
    }}
    dependedByKeys {{
      path
    }}
    jobNames
    opNames
    metadataEntries {{
{_METADATA_ENTRY_FRAGMENTS}
    }}
    assetMaterializations(limit: 1) {{
      runId
      timestamp
      partition
      metadataEntries {{
{_METADATA_ENTRY_FRAGMENTS}
      }}
    }}
"""

_ASSET_NODES_QUERY = f"""
query DatasynAssetCatalog {{
  assetNodes {{
{_ASSET_NODE_FIELDS}
  }}
}}
"""

_ASSET_NODE_DETAIL_QUERY = f"""
query DatasynAssetDetail($path: [String!]!) {{
  assetNodeOrError(assetKey: {{ path: $path }}) {{
    __typename
    ... on AssetNode {{
{_ASSET_NODE_FIELDS}
    }}
    ... on AssetNotFoundError {{
      message
    }}
  }}
}}
"""


def dagster_server_url() -> str:
    """Dagster webserver base URL from ``DAGSTER_URL`` (no path)."""
    return settings.dagster_url


def _key_path_to_str(path: list[str] | None) -> str:
    if not path:
        return ""
    return "/".join(str(p) for p in path if p)


def _tags_dict(tags: list[dict[str, Any]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in tags or []:
        if not isinstance(t, dict):
            continue
        k = str(t.get("key") or "").strip()
        v = str(t.get("value") or "").strip()
        if k:
            out[k] = v
    return out


def parse_metadata_entries(entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize Dagster ``metadataEntries`` (definition or materialization) to label/type/value."""
    out: list[dict[str, Any]] = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label") or "").strip()
        if not label:
            continue
        typename = str(e.get("__typename") or "MetadataEntry")
        value: Any = None
        if e.get("text") is not None:
            value = str(e["text"])
        elif e.get("url") is not None:
            value = str(e["url"])
        elif e.get("path") is not None:
            p = e["path"]
            value = "/".join(str(x) for x in p) if isinstance(p, list) else str(p)
        elif e.get("jsonString") is not None:
            value = e["jsonString"]
        elif e.get("floatValue") is not None:
            value = e["floatValue"]
        elif e.get("intValue") is not None:
            value = e["intValue"]
        elif e.get("boolValue") is not None:
            value = e["boolValue"]
        elif e.get("mdStr") is not None:
            value = e["mdStr"]
        if value is not None:
            out.append({"label": label, "type": typename, "value": value})
    return out


def metadata_lookup(entries: list[dict[str, Any]] | None) -> dict[str, str]:
    """Lowercase label → string value (for FQN inference and description fallbacks)."""
    return {str(e["label"]).lower(): str(e["value"]) for e in parse_metadata_entries(entries)}


def _owners_list(raw: list[dict[str, Any]] | None) -> list[str]:
    out: list[str] = []
    for o in raw or []:
        if not isinstance(o, dict):
            continue
        if o.get("__typename") == "UserAssetOwner" and o.get("email"):
            out.append(str(o["email"]))
        elif o.get("__typename") == "TeamAssetOwner" and o.get("team"):
            out.append(f"team:{o['team']}")
    return out


def infer_duckdb_fqn(
    asset_key_path: list[str],
    tags: dict[str, str],
    metadata: dict[str, str],
) -> str | None:
    """Best-effort map Dagster asset → DuckDB schema.table."""
    for key in ("fully_qualified_name", "fqn", "duckdb.fqn", "table_fqn"):
        if tags.get(key):
            return tags[key].strip()
        if metadata.get(key.replace(".", "_")) or metadata.get(key):
            v = metadata.get(key.replace(".", "_")) or metadata.get(key)
            if v and "." in v:
                return v.strip()

    for key in ("duckdb_table", "table", "table_name"):
        table = tags.get(key) or metadata.get(key)
        schema = tags.get("duckdb_schema") or tags.get("schema") or metadata.get("schema")
        if table and schema:
            return f"{schema.strip()}.{table.strip()}"
        if table and "." in table:
            return table.strip()

    path = [str(p) for p in asset_key_path if p]
    if len(path) >= 2 and path[0].lower() in ("bronze", "silver", "gold"):
        schema = path[0].lower()
        table = path[-1]
        return f"{schema}.{table}"

    if len(path) == 1 and tags.get("schema"):
        return f"{tags['schema'].strip()}.{path[0]}"

    return None


def _parse_latest_materialization(node: dict[str, Any]) -> dict[str, Any] | None:
    mats = node.get("assetMaterializations") or []
    if not isinstance(mats, list) or not mats:
        return None
    latest = mats[0]
    if not isinstance(latest, dict):
        return None
    entries = parse_metadata_entries(latest.get("metadataEntries"))
    ts = latest.get("timestamp")
    return {
        "run_id": latest.get("runId"),
        "timestamp": str(ts) if ts is not None else None,
        "partition": latest.get("partition"),
        "metadata": entries,
    }


def _parse_asset_node(node: dict[str, Any]) -> dict[str, Any]:
    key_path = (node.get("assetKey") or {}).get("path") or []
    if not isinstance(key_path, list):
        key_path = []
    key_path = [str(p) for p in key_path]
    tags = _tags_dict(node.get("tags"))
    def_metadata = metadata_lookup(node.get("metadataEntries"))
    latest_mat = _parse_latest_materialization(node)
    mat_metadata = (
        {str(e["label"]).lower(): str(e["value"]) for e in (latest_mat or {}).get("metadata") or []}
        if latest_mat
        else {}
    )
    combined_metadata = {**def_metadata, **mat_metadata}

    def _keys(field: str) -> list[str]:
        raw = node.get(field) or []
        out: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                p = item.get("path")
                if isinstance(p, list) and p:
                    out.append(_key_path_to_str([str(x) for x in p]))
        return out

    asset_key = _key_path_to_str(key_path)
    duckdb_fqn = infer_duckdb_fqn(key_path, tags, combined_metadata)
    definition_metadata = parse_metadata_entries(node.get("metadataEntries"))

    return {
        "dagster_asset_key": asset_key,
        "dagster_asset_path": key_path,
        "duckdb_fqn": duckdb_fqn,
        "description": (
            node.get("description") or combined_metadata.get("description") or ""
        )
        or None,
        "group_name": node.get("groupName"),
        "compute_kind": node.get("computeKind"),
        "kinds": list(node.get("kinds") or []),
        "is_materializable": node.get("isMaterializable"),
        "is_partitioned": node.get("isPartitioned"),
        "op_name": node.get("opName"),
        "owners": _owners_list(node.get("owners")),
        "tags": list(f"{k}={v}" for k, v in sorted(tags.items())),
        "job_names": list(node.get("jobNames") or []),
        "op_names": list(node.get("opNames") or []),
        "lineage_upstream": _keys("dependencyKeys"),
        "lineage_downstream": _keys("dependedByKeys"),
        "definition_metadata": definition_metadata,
        "latest_materialization": latest_mat,
        "metadata": combined_metadata,
    }


async def _post_graphql(*, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    url = dagster_graphql_url()
    async with httpx.AsyncClient(timeout=20.0) as client:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


async def fetch_dagster_asset_catalog() -> tuple[list[dict[str, Any]], str, str | None]:
    """Return (assets, status, error). status: ok | unavailable | error."""
    url = dagster_graphql_url()
    try:
        body = await _post_graphql(query=_ASSET_NODES_QUERY)
    except httpx.ConnectError:
        return [], "unavailable", f"Cannot reach Dagster GraphQL at {url}"
    except Exception as exc:
        logger.warning("Dagster GraphQL catalog failed (%s): %s", url, exc)
        return [], "error", str(exc)[:500]

    if body.get("errors"):
        msg = "; ".join(str(e.get("message", e)) for e in body["errors"][:3])
        return [], "error", msg[:500]

    nodes = (body.get("data") or {}).get("assetNodes") or []
    if not isinstance(nodes, list):
        return [], "error", "Unexpected GraphQL response shape"

    assets = [_parse_asset_node(n) for n in nodes if isinstance(n, dict)]
    logger.info("Dagster catalog: %s assets from %s", len(assets), url)
    return assets, "ok", None


async def fetch_dagster_asset_detail(asset_path: list[str]) -> dict[str, Any] | None:
    """Fetch one asset node by key path."""
    if not asset_path:
        return None
    url = dagster_graphql_url()
    try:
        body = await _post_graphql(
            query=_ASSET_NODE_DETAIL_QUERY,
            variables={"path": asset_path},
        )
    except Exception as exc:
        logger.warning("Dagster asset detail failed (%s): %s", url, exc)
        return None

    if body.get("errors"):
        return None
    node = (body.get("data") or {}).get("assetNodeOrError") or {}
    if node.get("__typename") != "AssetNode":
        return None
    return _parse_asset_node(node)


def dagster_assets_by_fqn(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index Dagster assets by inferred DuckDB FQN (multiple assets may collide — last wins)."""
    out: dict[str, dict[str, Any]] = {}
    for a in assets:
        fqn = a.get("duckdb_fqn")
        if fqn:
            out[str(fqn)] = a
    return out


def dagster_assets_by_key(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for a in assets:
        k = a.get("dagster_asset_key")
        if k:
            out[str(k)] = a
    return out
