"""Load catalog dataset summaries by invoking catalog-mcp tools (same MCP path as the Deep Agent)."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient

from agent.utils.agent_chat import _tool_connections

logger = logging.getLogger(__name__)

CATALOG_SERVER_KEY = "catalog"
CATALOG_LIST_TOOL = "catalog_list_datasets"


def _is_lc_text_block(x: Any) -> bool:
    return isinstance(x, dict) and x.get("type") == "text" and "text" in x


def _datasets_from_tool_result(raw: Any) -> list[Any]:
    """Normalize ``catalog_list_datasets`` output across MCP + LangChain formats.

    The catalog tool returns a JSON array string; langchain-mcp-adapters often surfaces
    LangChain **content blocks** ``[{"type": "text", "text": "[...]"}]`` or a ``ToolMessage``
    with the same ``content``. A bare list must not be assumed to be dataset rows.
    """
    if raw is None:
        raise ValueError("catalog tool returned empty")

    # ToolMessage(content=[...], artifact=...) from StructuredTool + MCP adapter
    try:
        from langchain_core.messages import ToolMessage
    except ImportError:
        ToolMessage = ()  # type: ignore[misc, assignment]

    if ToolMessage and isinstance(raw, ToolMessage):
        art = raw.artifact
        if art is not None:
            sc = getattr(art, "structured_content", None)
            if sc is None and isinstance(art, dict):
                sc = art.get("structured_content")
            if isinstance(sc, list):
                return sc
        return _datasets_from_tool_result(raw.content)

    if isinstance(raw, list):
        if len(raw) == 0:
            return []
        if all(_is_lc_text_block(x) for x in raw):
            combined = "".join(str(x.get("text", "")) for x in raw)
            return _datasets_from_tool_result(combined.strip())
        # List of dataset dicts (already parsed) — not LangChain text blocks
        if all(isinstance(x, dict) and not _is_lc_text_block(x) for x in raw):
            return raw
        # e.g. list of strings
        if all(isinstance(x, str) for x in raw):
            return _datasets_from_tool_result("\n".join(raw).strip())
        raise RuntimeError(
            f"catalog tool list shape not recognized (first keys: "
            f"{list(raw[0].keys()) if raw and isinstance(raw[0], dict) else type(raw[0])})"
        )

    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("Error:"):
            raise ValueError(text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"catalog tool returned invalid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("catalog tool JSON must be an array")
        return data

    if isinstance(raw, dict):
        if "datasets" in raw and isinstance(raw["datasets"], list):
            return raw["datasets"]
        if "content" in raw:
            return _datasets_from_tool_result(raw["content"])

    content = getattr(raw, "content", None)
    if content is not None and not isinstance(raw, dict):
        return _datasets_from_tool_result(content)

    raise RuntimeError(f"catalog tool returned unexpected type: {type(raw).__name__}")


async def fetch_catalog_datasets_via_mcp(
    *,
    limit: int = 48,
    service_name: str = "",
    database_name: str = "",
    schema_name: str = "",
) -> dict[str, Any]:
    """Call ``catalog_list_datasets`` on the HTTP MCP server named ``catalog`` in ``mcp.json``."""
    connections = _tool_connections()
    if CATALOG_SERVER_KEY not in connections:
        raise ValueError(
            f"mcp.json has no {CATALOG_SERVER_KEY!r} server; add catalog-mcp (see project mcp.json)."
        )
    subset = {CATALOG_SERVER_KEY: connections[CATALOG_SERVER_KEY]}
    client = MultiServerToolClient(subset, tool_name_prefix=True)
    tools = await client.get_tools()
    tool = next((t for t in tools if getattr(t, "name", None) == CATALOG_LIST_TOOL), None)
    if tool is None:
        names = sorted({getattr(t, "name", "") for t in tools})
        raise RuntimeError(
            f"MCP tool {CATALOG_LIST_TOOL!r} missing (tools from {CATALOG_SERVER_KEY!r}: {names})"
        )

    payload = {
        "service_name": service_name.strip(),
        "database_name": database_name.strip(),
        "schema_name": schema_name.strip(),
        "limit": limit,
    }
    try:
        raw = await tool.ainvoke(payload)
    except Exception as exc:
        logger.exception("catalog MCP tool %s failed", CATALOG_LIST_TOOL)
        raise RuntimeError(f"catalog MCP tool failed: {exc}") from exc

    datasets = _datasets_from_tool_result(raw)
    return {"ok": True, "count": len(datasets), "datasets": datasets}
