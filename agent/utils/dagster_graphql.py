"""Dagster GraphQL catalog client (webserver /graphql).

See https://docs.dagster.io/api/graphql
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_GRAPHQL_URL = "http://127.0.0.1:3001/graphql"

_ASSET_NODES_QUERY = """
query DatacyberAssetCatalog {
  assetNodes {
    id
    groupName
    description
    assetKey {
      path
    }
    tags {
      key
      value
    }
    dependencyKeys {
      path
    }
    dependedByKeys {
      path
    }
    jobNames
    opNames
    metadataEntries {
      label
      ... on TextMetadataEntry {
        text
      }
      ... on UrlMetadataEntry {
        url
      }
      ... on PathMetadataEntry {
        path
      }
    }
  }
}
"""

_ASSET_NODE_DETAIL_QUERY = """
query DatacyberAssetDetail($path: [String!]!) {
  assetNodeOrError(assetKey: { path: $path }) {
    __typename
    ... on AssetNode {
      id
      groupName
      description
      assetKey {
        path
      }
      tags {
        key
        value
      }
      dependencyKeys {
        path
      }
      dependedByKeys {
        path
      }
      jobNames
      opNames
      metadataEntries {
        label
        ... on TextMetadataEntry {
          text
        }
      }
    }
    ... on AssetNotFoundError {
      message
    }
  }
}
"""


def dagster_graphql_url() -> str:
    raw = (os.environ.get("DAGSTER_GRAPHQL_URL") or _DEFAULT_GRAPHQL_URL).strip()
    return raw.rstrip("/")


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


def _metadata_text(entries: list[dict[str, Any]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label") or "").strip().lower()
        text = e.get("text")
        if text is None and e.get("path"):
            text = "/".join(e["path"]) if isinstance(e.get("path"), list) else e.get("path")
        if label and text:
            out[label] = str(text)
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


def _parse_asset_node(node: dict[str, Any]) -> dict[str, Any]:
    key_path = (node.get("assetKey") or {}).get("path") or []
    if not isinstance(key_path, list):
        key_path = []
    key_path = [str(p) for p in key_path]
    tags = _tags_dict(node.get("tags"))
    metadata = _metadata_text(node.get("metadataEntries"))

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
    duckdb_fqn = infer_duckdb_fqn(key_path, tags, metadata)

    return {
        "dagster_asset_key": asset_key,
        "dagster_asset_path": key_path,
        "duckdb_fqn": duckdb_fqn,
        "description": (node.get("description") or metadata.get("description") or "") or None,
        "group_name": node.get("groupName"),
        "tags": list(f"{k}={v}" for k, v in sorted(tags.items())),
        "job_names": list(node.get("jobNames") or []),
        "op_names": list(node.get("opNames") or []),
        "lineage_upstream": _keys("dependencyKeys"),
        "lineage_downstream": _keys("dependedByKeys"),
        "metadata": metadata,
    }


async def fetch_dagster_asset_catalog() -> tuple[list[dict[str, Any]], str, str | None]:
    """Return (assets, status, error). status: ok | unavailable | error."""
    url = dagster_graphql_url()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json={"query": _ASSET_NODES_QUERY})
            resp.raise_for_status()
            body = resp.json()
    except httpx.ConnectError:
        return [], "unavailable", f"Cannot reach Dagster GraphQL at {url}"
    except Exception as exc:
        logger.warning("Dagster GraphQL catalog failed: %s", exc)
        return [], "error", str(exc)[:500]

    if body.get("errors"):
        msg = "; ".join(str(e.get("message", e)) for e in body["errors"][:3])
        return [], "error", msg[:500]

    nodes = (body.get("data") or {}).get("assetNodes") or []
    if not isinstance(nodes, list):
        return [], "error", "Unexpected GraphQL response shape"

    assets = [_parse_asset_node(n) for n in nodes if isinstance(n, dict)]
    return assets, "ok", None


async def fetch_dagster_asset_detail(asset_path: list[str]) -> dict[str, Any] | None:
    """Fetch one asset node by key path."""
    if not asset_path:
        return None
    url = dagster_graphql_url()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                json={
                    "query": _ASSET_NODE_DETAIL_QUERY,
                    "variables": {"path": asset_path},
                },
            )
            resp.raise_for_status()
            body = resp.json()
    except Exception:
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
