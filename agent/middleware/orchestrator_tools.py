"""Block MCP warehouse tools on the orchestrator (main) thread."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from agent.deep_agent_constants import DATA_ANALYST_SUBAGENT_TYPE, QUERY_SUBAGENT_TYPE

MCP_TOOL_PREFIXES = ("duckdb_", "dagster_", "storage_")

_DELEGATION_HINT = (
    f"MCP tools are **not** available on the orchestrator thread. "
    f"Spawn **`task(subagent_type=\"{QUERY_SUBAGENT_TYPE}\")`** (or **`{DATA_ANALYST_SUBAGENT_TYPE}`** "
    "for warehouse-only isolation) with the full user goal, language, and expected return shape."
)


def is_mcp_tool_name(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in MCP_TOOL_PREFIXES)


def _blocked_message(tool_name: str) -> str:
    return f"Error: `{tool_name}` blocked on orchestrator. {_DELEGATION_HINT}"


class OrchestratorMcpGuardMiddleware(AgentMiddleware[Any, Any, Any]):
    """Hide MCP tools from the model and reject execution if they leak through."""

    def wrap_model_call(self, request, handler):
        if request.tools:
            filtered = [t for t in request.tools if not is_mcp_tool_name(_tool_name(t) or "")]
            request = request.override(tools=filtered)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        if request.tools:
            filtered = [t for t in request.tools if not is_mcp_tool_name(_tool_name(t) or "")]
            request = request.override(tools=filtered)
        return await handler(request)

    def wrap_tool_call(self, request, handler):
        name = _tool_call_name(request)
        if name and is_mcp_tool_name(name):
            return ToolMessage(
                content=_blocked_message(name),
                tool_call_id=_tool_call_id(request),
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        name = _tool_call_name(request)
        if name and is_mcp_tool_name(name):
            return ToolMessage(
                content=_blocked_message(name),
                tool_call_id=_tool_call_id(request),
            )
        return await handler(request)


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        raw = tool.get("name")
        return raw if isinstance(raw, str) else None
    raw = getattr(tool, "name", None)
    return raw if isinstance(raw, str) else None


def _tool_call_name(request: Any) -> str | None:
    tool_call = getattr(request, "tool_call", None) or {}
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool_call, "name", None)
    return name if isinstance(name, str) else None


def _tool_call_id(request: Any) -> str:
    tool_call = getattr(request, "tool_call", None) or {}
    if isinstance(tool_call, dict):
        return str(tool_call.get("id") or "")
    return str(getattr(tool_call, "id", "") or "")
