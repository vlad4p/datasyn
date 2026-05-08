"""Parse DuckDB ``get_schema`` pipe text and group tables by medallion schema for the UI."""

from __future__ import annotations

from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient

from agent.utils.mcp_connections import load_mcp_tool_connections

_MEDALLION = ("bronze", "silver", "gold")


def _extract_tool_text(raw: Any) -> str:
    """Collapse MCP / LangChain tool output into a plain string."""

    if raw is None:
        raise ValueError("tool returned empty")

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

    raise RuntimeError(f"tool returned unexpected type: {type(raw).__name__}")


def parse_duckdb_get_schema_text(text: str) -> list[dict[str, str]]:
    """Parse MCP ``get_schema`` pipe-separated output into rows."""
    rows: list[dict[str, str]] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("Error:"):
            continue
        if "table_schema" in ln and "table_name" in ln:
            continue
        if set(ln) <= {"-", "|", " "} or all(c in "-|" or c.isspace() for c in ln):
            continue
        if "|" not in ln:
            continue
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 3:
            continue
        rows.append(
            {
                "schema": parts[0],
                "name": parts[1],
                "table_type": parts[2],
            }
        )
    return rows


def group_medallion_layers(
    tables: list[dict[str, str]],
) -> dict[str, Any]:
    """Split tables into bronze/silver/gold buckets; remainder under ``other``."""
    layers: dict[str, list[dict[str, str]]] = {k: [] for k in _MEDALLION}
    other: list[dict[str, str]] = []
    for r in tables:
        s = (r.get("schema") or "").strip().lower()
        entry = {"name": r["name"], "table_type": r.get("table_type", "")}
        if s in layers:
            layers[s].append(entry)
        else:
            other.append(
                {
                    "schema": r.get("schema", ""),
                    "name": r["name"],
                    "table_type": r.get("table_type", ""),
                }
            )
    for k in _MEDALLION:
        layers[k].sort(key=lambda x: x["name"].lower())
    other.sort(key=lambda x: (x.get("schema", "").lower(), x["name"].lower()))
    return {"layers": layers, "other": other}


async def fetch_duckdb_schema_text() -> str:
    """Call MCP ``duckdb_get_schema`` and return plain text."""
    client = MultiServerToolClient(load_mcp_tool_connections(), tool_name_prefix=True)
    tools = await client.get_tools()
    for t in tools:
        if str(getattr(t, "name", "") or "").strip() == "duckdb_get_schema":
            raw = await t.ainvoke({})
            return _extract_tool_text(raw)
    raise RuntimeError("duckdb_get_schema tool not found (check mcp.json duckdb server)")


async def warehouse_tables_payload() -> dict[str, Any]:
    """Schema suitable for ``GET /health/warehouse/tables``."""
    text = await fetch_duckdb_schema_text()
    tables = parse_duckdb_get_schema_text(text)
    grouped = group_medallion_layers(tables)
    return {
        "status": "ok",
        "layers": grouped["layers"],
        "other": grouped["other"],
        "raw_line_count": len(tables),
    }
