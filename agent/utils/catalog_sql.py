"""SQL composition helpers for the brain's catalog queries.

Metadata catalog tools live on **dagster-mcp** (see ``mcp_servers/dagster-mcp/server.py``):

* ``dagster_catalog_get_schema`` — ``public`` tables / columns / foreign keys.
* ``dagster_catalog_execute_query`` — single ``SELECT`` / ``INSERT`` / ``UPDATE`` /
  ``DELETE`` (no DDL, no multiple statements).

There is **no** ``catalog_list_datasets`` / ``catalog_search_datasets`` /
``catalog_register_or_update_dataset`` / ``catalog_set_lineage`` tool anymore:
those dataset-shaped operations are composed as SQL by the brain (this module
and the ``./skills/catalog-sql/SKILL.md``). The HTTP path ``GET
/catalog/datasets`` goes through :func:`build_list_datasets_sql` +
``dagster_catalog_execute_query``.

The SQL shape matches what's documented in ``skills/catalog-sql/SKILL.md`` so
agent traces and the refresh button end up running identical queries.
"""

from __future__ import annotations

import json
from typing import Any


__all__ = [
    "build_list_datasets_sql",
    "build_get_dataset_sql",
    "build_search_datasets_sql",
    "summarize_entity_json",
]


_MAX_FILTER_LEN = 128
_MAX_QUERY_LEN = 256
_LIMIT_CAP = 200


def _sql_literal(value: str, *, field: str, max_len: int = _MAX_FILTER_LEN) -> str:
    """Escape *value* for inclusion inside a single-quoted Postgres string literal.

    * Doubles single quotes (``'`` → ``''``), which is the only escape needed when
      the string is wrapped in ``'…'`` and ``standard_conforming_strings`` is on
      (the Postgres default).
    * Rejects NUL bytes — Postgres doesn't allow them in text anyway.
    * Caps length as a cheap defense against runaway inputs.
    """

    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{field!s} must be a string, got {type(value).__name__}")
    text = value.strip()
    if "\x00" in text:
        raise ValueError(f"{field!s} must not contain NUL bytes")
    if len(text) > max_len:
        raise ValueError(f"{field!s} too long (> {max_len} chars)")
    return text.replace("'", "''")


def _clamp_limit(limit: int, *, default: int = 48) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, _LIMIT_CAP))


def build_list_datasets_sql(
    *,
    service_name: str = "",
    database_name: str = "",
    schema_name: str = "",
    limit: int = 48,
) -> str:
    """SQL for the UI catalog panel / ``GET /catalog/datasets``.

    Empty filters become no-ops via the ``'<value>' = '' OR …`` pattern (same
    shape as ``skills/catalog-sql/SKILL.md``).

    * ``service_name`` is matched with ``ILIKE '%…%'`` (substring, case-insensitive).
    * ``database_name`` / ``schema_name`` are matched by exact equality.

    Rows include the ``entity_json`` document plus timestamps so the caller
    (``summarize_entity_json``) can build a compact UI summary without a second
    query.
    """

    svc = _sql_literal(service_name, field="service_name")
    db = _sql_literal(database_name, field="database_name")
    sch = _sql_literal(schema_name, field="schema_name")
    n = _clamp_limit(limit)
    return (
        "SELECT id, fully_qualified_name, entity_json, updated_at, created_at\n"
        "FROM dataset_entity\n"
        "WHERE "
        f"('{svc}' = '' OR entity_json->'service'->>'name' ILIKE '%' || '{svc}' || '%')\n"
        f"  AND ('{db}' = '' OR entity_json->'database'->>'name' = '{db}')\n"
        f"  AND ('{sch}' = '' OR entity_json->'schema'->>'name' = '{sch}')\n"
        "ORDER BY updated_at DESC NULLS LAST, id DESC\n"
        f"LIMIT {n};"
    )


def build_get_dataset_sql(fully_qualified_name: str) -> str:
    """SQL for a single dataset by FQN (returns at most one row)."""

    fqn = _sql_literal(fully_qualified_name, field="fully_qualified_name", max_len=512)
    if not fqn:
        raise ValueError("fully_qualified_name is required")
    return (
        "SELECT id, fully_qualified_name, entity_json, updated_at, created_at\n"
        "FROM dataset_entity\n"
        f"WHERE fully_qualified_name = '{fqn}'\n"
        "LIMIT 1;"
    )


def build_search_datasets_sql(query: str, *, limit: int = 20) -> str:
    """Full-text search over ``dataset_entity.search_tsv`` (generated column)."""

    q = _sql_literal(query, field="query", max_len=_MAX_QUERY_LEN)
    if not q:
        raise ValueError("query is required for catalog search")
    n = _clamp_limit(limit, default=20)
    return (
        "SELECT id, fully_qualified_name, entity_json,\n"
        f"       ts_rank_cd(search_tsv, plainto_tsquery('simple', '{q}')) AS rank,\n"
        "       updated_at, created_at\n"
        "FROM dataset_entity\n"
        f"WHERE search_tsv @@ plainto_tsquery('simple', '{q}')\n"
        "ORDER BY rank DESC, updated_at DESC NULLS LAST\n"
        f"LIMIT {n};"
    )


def _as_entity_dict(value: Any) -> dict[str, Any]:
    """Normalize ``entity_json`` to a ``dict``.

    psycopg returns JSONB as a Python ``dict`` directly, but older data that was
    double-encoded (stored as a JSON string) would come back as ``str``. Handle
    both so the UI never sees a mismatch.
    """

    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _len_if_list(value: Any) -> int | None:
    return len(value) if isinstance(value, list) else None


def summarize_entity_json(row: dict[str, Any]) -> dict[str, Any]:
    """Map a ``dataset_entity`` row to the UI ``CatalogDatasetSummary`` shape.

    Keeps the TypeScript type in ``ui/src/api.ts`` as the source of truth: FQN,
    service / database / schema blocks, column + tag counts, timestamps.
    """

    ej = _as_entity_dict(row.get("entity_json"))

    service = ej.get("service") if isinstance(ej.get("service"), dict) else None
    database = ej.get("database") if isinstance(ej.get("database"), dict) else None
    schema = ej.get("schema") if isinstance(ej.get("schema"), dict) else None

    row_id = ej.get("id") if ej.get("id") is not None else row.get("id")
    fqn = ej.get("fullyQualifiedName") or row.get("fully_qualified_name")

    return {
        "id": str(row_id) if row_id is not None else None,
        "fullyQualifiedName": fqn,
        "name": ej.get("name"),
        "displayName": ej.get("displayName"),
        "description": ej.get("description"),
        "tableType": ej.get("tableType"),
        "service": service,
        "database": database,
        "schema": schema,
        "columnCount": _len_if_list(ej.get("columns")),
        "tagCount": _len_if_list(ej.get("tags")),
        "updatedAt": ej.get("updatedAt") or row.get("updated_at"),
        "createdAt": ej.get("createdAt") or row.get("created_at"),
    }
