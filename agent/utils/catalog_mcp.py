"""Load catalog dataset summaries by running SQL through ``catalog_execute_query``.

The ``catalog`` MCP server no longer exposes a ``catalog_list_datasets`` tool.
Listing is composed as SQL in :mod:`agent.utils.catalog_sql` and executed via
``catalog_execute_query``; this module bridges the HTTP endpoint
(``GET /catalog/datasets`` in ``agent.main``) and the MCP client so the brain
and the UI Refresh button hit the database through the exact same path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient

from agent.utils.agent_chat import _tool_connections
from agent.utils.catalog_sql import build_list_datasets_sql, summarize_entity_json

logger = logging.getLogger(__name__)

CATALOG_SERVER_KEY = "catalog"
CATALOG_EXECUTE_QUERY_TOOL = "catalog_execute_query"


def _extract_tool_text(raw: Any) -> str:
    """Collapse MCP / LangChain tool output into a plain string (expected: JSON).

    ``catalog_execute_query`` returns a JSON string. ``langchain-mcp-adapters``
    may surface that as:

    * a raw ``str``
    * a list of LangChain content blocks ``[{"type": "text", "text": "..."}]``
    * a ``ToolMessage`` whose ``content`` is one of the above
    * a dict with a ``content`` key (rare — older adapter versions)

    Any other shape is surfaced as a ``RuntimeError`` with the observed type so
    debugging doesn't require guessing.
    """

    if raw is None:
        raise ValueError("catalog_execute_query returned empty")

    try:
        from langchain_core.messages import ToolMessage
    except ImportError:
        ToolMessage = ()  # type: ignore[assignment]

    if ToolMessage and isinstance(raw, ToolMessage):
        return _extract_tool_text(raw.content)

    if isinstance(raw, str):
        return raw

    if isinstance(raw, list):
        parts: list[str] = []
        for x in raw:
            if isinstance(x, dict) and x.get("type") == "text" and "text" in x:
                parts.append(str(x["text"]))
            elif isinstance(x, str):
                parts.append(x)
            else:
                parts.append(str(x))
        return "".join(parts)

    if isinstance(raw, dict):
        if "content" in raw:
            return _extract_tool_text(raw["content"])

    content = getattr(raw, "content", None)
    if content is not None and not isinstance(raw, dict):
        return _extract_tool_text(content)

    raise RuntimeError(f"catalog_execute_query returned unexpected type: {type(raw).__name__}")


def _parse_rows(text: str) -> list[dict[str, Any]]:
    """Parse the JSON envelope ``catalog_execute_query`` returns into ``rows``."""

    trimmed = text.strip()
    if not trimmed:
        return []
    try:
        payload = json.loads(trimmed)
    except json.JSONDecodeError as exc:
        raise ValueError(f"catalog_execute_query returned invalid JSON: {exc}") from exc

    if isinstance(payload, dict) and "error" in payload:
        raise ValueError(f"catalog_execute_query error: {payload['error']}")

    if not isinstance(payload, dict):
        raise ValueError(
            f"catalog_execute_query returned unexpected JSON: {type(payload).__name__}"
        )

    rows = payload.get("rows")
    if rows is None:
        raise ValueError(
            "catalog_execute_query envelope missing 'rows'; "
            f"keys={sorted(payload.keys())[:8]}"
        )
    if not isinstance(rows, list):
        raise ValueError("catalog_execute_query 'rows' must be an array")
    return [r for r in rows if isinstance(r, dict)]


async def fetch_catalog_datasets_via_mcp(
    *,
    limit: int = 48,
    service_name: str = "",
    database_name: str = "",
    schema_name: str = "",
) -> dict[str, Any]:
    """Run the list-datasets SQL through ``catalog_execute_query`` and summarize.

    Returns ``{"ok": True, "count": N, "datasets": [...summary...]}`` on success
    where each summary row matches the ``CatalogDatasetSummary`` TypeScript
    contract in ``ui/src/api.ts``.

    Raises:
      * ``ValueError`` — bad filter input or invalid tool response.
      * ``RuntimeError`` — tool missing or MCP call failed; the HTTP layer maps
        these to 502 / 503 respectively.
    """

    connections = _tool_connections()
    if CATALOG_SERVER_KEY not in connections:
        raise ValueError(
            f"mcp.json has no {CATALOG_SERVER_KEY!r} server; add catalog-mcp (see project mcp.json)."
        )

    subset = {CATALOG_SERVER_KEY: connections[CATALOG_SERVER_KEY]}
    client = MultiServerToolClient(subset, tool_name_prefix=True)
    tools = await client.get_tools()
    tool = next((t for t in tools if getattr(t, "name", None) == CATALOG_EXECUTE_QUERY_TOOL), None)
    if tool is None:
        names = sorted({getattr(t, "name", "") for t in tools})
        raise RuntimeError(
            f"MCP tool {CATALOG_EXECUTE_QUERY_TOOL!r} missing "
            f"(tools from {CATALOG_SERVER_KEY!r}: {names})"
        )

    sql = build_list_datasets_sql(
        service_name=service_name,
        database_name=database_name,
        schema_name=schema_name,
        limit=limit,
    )

    try:
        raw = await tool.ainvoke({"sql": sql, "max_rows": int(limit)})
    except Exception as exc:
        logger.exception("catalog MCP tool %s failed", CATALOG_EXECUTE_QUERY_TOOL)
        raise RuntimeError(f"catalog MCP tool failed: {exc}") from exc

    text = _extract_tool_text(raw)
    rows = _parse_rows(text)
    datasets = [summarize_entity_json(r) for r in rows]
    return {"ok": True, "count": len(datasets), "datasets": datasets}
