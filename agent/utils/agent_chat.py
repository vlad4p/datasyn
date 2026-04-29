"""One-turn chat: load remote HTTP tool servers and run the Deep Agent.

**Flow (UI → LiteLLM)** — only the **brain** talks to LiteLLM; the browser never sends ``LITELLM_KEY``.

1. Browser: ``POST /api/agent/chat`` (Vite proxy) → brain ``POST /agent/chat`` with JSON ``{ "message": "...", "locale": "en"|"es" }`` (optional ``locale``, default ``en``).
2. Brain: ``run_agent_chat_turn`` loads MCP tools from ``mcp.json``, builds ``create_deep_agent`` with
   ``build_chat_model()`` → ``langchain_openai.ChatOpenAI`` (``base_url`` = LiteLLM proxy, ``api_key`` = ``LITELLM_KEY``).
3. Agent graph invokes that model for LLM turns; MCP tools hit ``duckdb-mcp`` etc. No separate "model service" in front.

If LiteLLM returns ``401 Received API Key = sk-…XXXX``, ``XXXX`` is the key **this process** sent in the
``Authorization: Bearer`` header — compare to ``litellm_key_suffix`` on ``GET /health``. If your code hardcodes a
different key but the error still shows an old suffix, the running container/image is stale: rebuild the brain.
"""

from __future__ import annotations

import json
import logging
import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient
from opentelemetry import trace

from agent.graph import build_agent
from agent.utils.messages import resolve_assistant_reply, summarize_messages_for_debug
from agent.utils.mcp_tool_log import MCPToolResponseLogger
from agent.utils.langfuse_tracing import (
    build_langfuse_run_metadata,
    create_langchain_callback_handler,
    finalize_root_observation,
    flush_langfuse,
    root_chat_observation,
)
from agent.config import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _project_root() -> Path:
    return settings.project_root


def _tool_connections() -> dict[str, Any]:
    """HTTP connection map from ``mcp.json`` only (``mcpServers`` or ``servers`` block)."""
    cfg_path = _project_root() / "mcp.json"
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"Missing {cfg_path}: define MCP HTTP servers there (see project mcp.json)."
        )
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    block = raw.get("mcpServers") or raw.get("servers")
    if not isinstance(block, dict) or not block:
        raise ValueError(
            "mcp.json must contain a non-empty object under 'mcpServers' or 'servers'."
        )
    connections: dict[str, Any] = {}
    for name, spec in block.items():
        if not isinstance(spec, dict):
            continue
        url = spec.get("url")
        if not url:
            continue
        transport = spec.get("transport") or "http"
        connections[str(name)] = {"transport": transport, "url": str(url)}
    if not connections:
        raise ValueError("mcp.json: no entries with a 'url' field.")
    return connections


@dataclass(frozen=True)
class ChatTurnResult:
    """Result of a single user message → agent run."""

    reply: str
    request_id: str
    debug: dict[str, Any] | None


def _is_empty_generation_index_error(exc: BaseException) -> bool:
    """Detect LangChain empty-generation access (llm_result.generations[0][0])."""
    msg = str(exc).lower()
    return isinstance(exc, IndexError) and "list index out of range" in msg


async def _ainvoke_with_empty_generation_retry(
    agent: Any,
    payload: dict[str, Any],
    *,
    config: dict[str, Any],
    request_id: str,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Retry once when provider returns an empty generations payload."""
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await agent.ainvoke(payload, config=config)
        except Exception as exc:
            if not _is_empty_generation_index_error(exc) or attempt >= max_attempts:
                raise
            last_exc = exc
            logger.warning(
                "[%s] empty model generations on attempt %s/%s; retrying",
                request_id,
                attempt,
                max_attempts,
            )
            await asyncio.sleep(0.35 * attempt)
    assert last_exc is not None
    raise last_exc


async def run_agent_chat_turn(
    message: str,
    *,
    request_id: str | None = None,
    langfuse_session_id: str | None = None,
    langfuse_user_id: str | None = None,
    response_locale: str = "en",
) -> ChatTurnResult:
    """Load MCP tools, run the deep agent, return reply and optional debug payload."""
    rid = request_id or str(uuid.uuid4())
    t0 = time.perf_counter()
    steps: list[dict[str, Any]] = []

    def record(step: str, **extra: Any) -> None:
        entry = {
            "step": step,
            "ms_from_start": round((time.perf_counter() - t0) * 1000, 2),
            **extra,
        }
        steps.append(entry)
        logger.info("[%s] pipeline %s %s", rid, step, extra)

    with tracer.start_as_current_span("brain.run_agent_chat_turn") as span:
        span.set_attribute("datacyber.request_id", rid)
        span.set_attribute("datacyber.message_chars", len(message))
        span.set_attribute("datacyber.response_locale", response_locale or "en")

        logger.info("[%s] chat_turn start message_chars=%s", rid, len(message))

        connections = _tool_connections()
        logger.info("[%s] mcp.json server keys=%s", rid, list(connections.keys()))
        for key, spec in connections.items():
            logger.info("[%s] mcp server %r url=%s", rid, key, spec.get("url"))
        record("mcp_config_loaded", servers=list(connections.keys()))

        client = MultiServerToolClient(connections, tool_name_prefix=True)
        t_tools = time.perf_counter()
        with tracer.start_as_current_span("brain.mcp_get_tools"):
            tools = await client.get_tools()
        tools_ms = round((time.perf_counter() - t_tools) * 1000, 2)
        tool_names = sorted([getattr(t, "name", repr(t)) for t in tools])
        logger.info(
            "[%s] MCP get_tools done count=%s ms=%s names=%s",
            rid,
            len(tools),
            tools_ms,
            tool_names,
        )
        record("mcp_get_tools", tool_count=len(tools), tool_names=tool_names, ms=tools_ms)
        span.set_attribute("datacyber.mcp_tool_count", len(tool_names))

        loc = "es" if (response_locale or "en").strip().lower() == "es" else "en"
        record("response_locale", locale=loc)
        agent = build_agent(tools, response_locale=loc)
        record("build_agent_done")

        lf_handler = create_langchain_callback_handler()
        callbacks: list[Any] = [MCPToolResponseLogger(rid)]
        invoke_config: dict[str, Any] = {"callbacks": callbacks}
        if lf_handler:
            callbacks.append(lf_handler)
            invoke_config["metadata"] = build_langfuse_run_metadata(
                request_id=rid,
                session_id=langfuse_session_id,
                user_id=langfuse_user_id,
            )
            invoke_config["run_name"] = "datacyber-agent-chat"
            record("langfuse_callbacks_attached", tags=invoke_config["metadata"].get("langfuse_tags"))

        t_invoke = time.perf_counter()
        try:
            with tracer.start_as_current_span("brain.agent_ainvoke"):
                if lf_handler:
                    from langfuse import propagate_attributes

                    with root_chat_observation(request_id=rid, user_message=message) as root_obs:
                        with propagate_attributes(
                            session_id=langfuse_session_id,
                            user_id=langfuse_user_id,
                        ):
                            state = await _ainvoke_with_empty_generation_retry(
                                agent,
                                {"messages": [HumanMessage(content=message)]},
                                config=invoke_config,
                                request_id=rid,
                            )
                        reply = resolve_assistant_reply(state)
                        finalize_root_observation(root_obs, reply=reply)
                else:
                    state = await _ainvoke_with_empty_generation_retry(
                        agent,
                        {"messages": [HumanMessage(content=message)]},
                        config=invoke_config,
                        request_id=rid,
                    )
                    reply = resolve_assistant_reply(state)
        finally:
            flush_langfuse()

        invoke_ms = round((time.perf_counter() - t_invoke) * 1000, 2)
        logger.info("[%s] agent.ainvoke finished ms=%s state_keys=%s", rid, invoke_ms, list(state.keys()))
        record("agent_ainvoke", ms=invoke_ms)
        span.set_attribute("datacyber.invoke_ms", invoke_ms)

        msg_summary = summarize_messages_for_debug(state)
        logger.info("[%s] message_count=%s", rid, msg_summary.get("message_count"))
        for row in msg_summary.get("timeline", []):
            logger.info("[%s] timeline %s", rid, row)

        if not reply.strip():
            logger.warning(
                "[%s] empty assistant reply after resolve_assistant_reply; check LiteLLM and graph output",
                rid,
            )

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        logger.info(
            "[%s] chat_turn done reply_chars=%s total_ms=%s pipeline_debug=%s",
            rid,
            len(reply),
            total_ms,
            settings.pipeline_debug,
        )
        span.set_attribute("datacyber.total_ms", total_ms)
        span.set_attribute("datacyber.reply_chars", len(reply))

        debug: dict[str, Any] | None = None
        if settings.pipeline_debug:
            debug = {
                "request_id": rid,
                "total_ms": total_ms,
                "invoke_ms": invoke_ms,
                "tool_names": tool_names,
                "messages": msg_summary,
                "skills": (
                    "Deep Agents `skills=[\"/skills/\"]` (parent dir; SkillsMiddleware auto-discovers "
                    "every subdir with a SKILL.md — e.g. analyze-indec-eph-hogar, ingest-indec-mercadolaboral, "
                    "scrape-indec-mercado-laboral, update-catalog, catalog-sql). "
                    "There is no separate skill HTTP endpoint."
                ),
                "steps": steps,
            }

        return ChatTurnResult(reply=reply, request_id=rid, debug=debug)
