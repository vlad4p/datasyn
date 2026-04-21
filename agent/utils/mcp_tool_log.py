"""Terminal logging for MCP tool calls (LangChain callbacks → brain stderr)."""

from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger("agent.mcp_tools")

# Cap response body size in logs (full tool output can be huge).
_MAX_OUT = max(500, int(os.environ.get("MCP_TOOL_RESPONSE_LOG_MAX", "12000")))


class MCPToolResponseLogger(AsyncCallbackHandler):
    """Logs each tool start/end to the terminal; use for DuckDB MCP (`duckdb_*`) visibility."""

    def __init__(self, request_id: str) -> None:
        super().__init__()
        self.request_id = request_id

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
        inp = input_str or ""
        preview = inp[:4000] + ("…" if len(inp) > 4000 else "")
        logger.info(
            "[%s] MCP tool START name=%s run_id=%s input_chars=%s\nINPUT:\n%s",
            self.request_id,
            name,
            run_id,
            len(inp),
            preview,
        )

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name", "?")
        text = output if isinstance(output, str) else repr(output)
        if len(text) > _MAX_OUT:
            body = text[:_MAX_OUT] + f"\n... (truncated; MCP_TOOL_RESPONSE_LOG_MAX={_MAX_OUT})"
        else:
            body = text
        logger.info(
            "[%s] MCP tool RESPONSE name=%s run_id=%s output_chars=%s\nOUTPUT:\n%s",
            self.request_id,
            name,
            run_id,
            len(text),
            body,
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
        name = kwargs.get("name", "?")
        logger.error(
            "[%s] MCP tool ERROR name=%s run_id=%s: %s",
            self.request_id,
            name,
            run_id,
            error,
        )
