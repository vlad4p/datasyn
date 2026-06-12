"""Terminal logging for MCP tool calls (LangChain callbacks → brain stderr)."""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

from agent.utils.langfuse_tracing import record_mcp_tool_observation

logger = logging.getLogger("agent.mcp_tools")

# Cap response body size in logs (full tool output can be huge).
_MAX_OUT = max(500, int(os.environ.get("MCP_TOOL_RESPONSE_LOG_MAX", "12000")))


def _thread_hint(tags: list[str] | None, parent_run_id: UUID | None) -> str:
    if tags:
        for tag in tags:
            if "subagent" in tag.lower() or tag.startswith("graph:"):
                return "subagent"
    return "main" if parent_run_id is None else "nested"


class MCPToolResponseLogger(AsyncCallbackHandler):
    """Logs each tool start/end to the terminal; enriches Langfuse when enabled."""

    def __init__(self, request_id: str) -> None:
        super().__init__()
        self.request_id = request_id
        self._tool_names: dict[UUID, str] = {}
        self._langfuse_tool_obs: dict[UUID, Any] = {}

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = serialized.get("name", "?")
        self._tool_names[run_id] = str(name)
        inp = input_str or ""
        preview = inp[:4000] + ("…" if len(inp) > 4000 else "")
        thread = _thread_hint(tags, parent_run_id)
        logger.info(
            "[%s] MCP tool START name=%s thread=%s run_id=%s input_chars=%s\nINPUT:\n%s",
            self.request_id,
            name,
            thread,
            run_id,
            len(inp),
            preview,
        )
        obs = record_mcp_tool_observation(
            tool_name=str(name),
            phase="start",
            request_id=self.request_id,
            input_preview=preview,
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            thread=thread,
            run_id=str(run_id),
        )
        if obs is not None:
            self._langfuse_tool_obs[run_id] = obs

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name") or self._tool_names.get(run_id, "?")
        text = output if isinstance(output, str) else repr(output)
        if len(text) > _MAX_OUT:
            body = text[:_MAX_OUT] + f"\n... (truncated; MCP_TOOL_RESPONSE_LOG_MAX={_MAX_OUT})"
        else:
            body = text
        thread = _thread_hint(tags, parent_run_id)
        logger.info(
            "[%s] MCP tool RESPONSE name=%s thread=%s run_id=%s output_chars=%s\nOUTPUT:\n%s",
            self.request_id,
            name,
            thread,
            run_id,
            len(text),
            body,
        )
        record_mcp_tool_observation(
            tool_name=str(name),
            phase="end",
            request_id=self.request_id,
            output_preview=body,
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            thread=thread,
            run_id=str(run_id),
            tool_observation=self._langfuse_tool_obs.pop(run_id, None),
        )

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name") or self._tool_names.get(run_id, "?")
        thread = _thread_hint(tags, parent_run_id)
        logger.error(
            "[%s] MCP tool ERROR name=%s thread=%s run_id=%s: %s",
            self.request_id,
            name,
            thread,
            run_id,
            error,
        )
        record_mcp_tool_observation(
            tool_name=str(name),
            phase="error",
            request_id=self.request_id,
            output_preview=str(error)[:_MAX_OUT],
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            thread=thread,
            run_id=str(run_id),
            tool_observation=self._langfuse_tool_obs.pop(run_id, None),
        )
