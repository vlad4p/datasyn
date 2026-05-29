"""One-turn chat: load remote HTTP tool servers and run the Deep Agent.

**Flow (UI → LLM)** — only the **brain** calls the configured provider; the browser never sends API keys.

1. Browser: ``POST /api/agent/chat`` (Vite proxy) → brain ``POST /agent/chat`` with JSON
   ``{ "message": "...", "locale": "en"|"es", "history": [ { "role": "user"|"assistant", "content": "..." }, ... ] }``.
   ``history`` holds prior turns only; the brain merges them into LangGraph ``messages`` before the new user message (same shape as Deep Agent state).
2. Brain: ``run_agent_chat_turn`` loads MCP tools from ``mcp.json``, builds ``create_deep_agent`` with
   ``build_chat_model()`` — **LiteLLM** (``langchain_openai.ChatOpenAI`` + ``LITELLM_KEY``) when ``MODEL_PROVIDER=litellm`` (default), **OpenRouter** (``ChatOpenAI`` + ``OPENROUTER_API_KEY``, base ``OPENROUTER_BASE_URL`` or ``https://openrouter.ai/api/v1``) when ``MODEL_PROVIDER=openrouter``, or **Gemini** (``langchain_google_genai.ChatGoogleGenerativeAI`` + ``GEMINI_API_KEY``) when ``MODEL_PROVIDER=gemini``.
3. Agent graph invokes that model for LLM turns; MCP tools hit ``duckdb-mcp`` etc.

If LiteLLM returns ``401 Received API Key = sk-…XXXX``, ``XXXX`` is the key **this process** sent — compare to ``litellm_key_suffix`` on ``GET /health``.
"""

from __future__ import annotations

import logging
import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient
from opentelemetry import trace

from agent.graph import build_agent
from agent.utils.chat_history import build_agent_invoke_messages
from agent.utils.chat_stream_events import langgraph_stream_part_to_events
from agent.utils.mcp_connections import load_mcp_tool_connections
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
    """HTTP connection map from ``mcp.json`` (with host-side URL rewrites when not in Docker)."""
    return load_mcp_tool_connections(_project_root())


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
    history: list[dict[str, Any]] | None = None,
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
        span.set_attribute("datasyn.request_id", rid)
        span.set_attribute("datasyn.message_chars", len(message))
        span.set_attribute("datasyn.history_turns", len(history or []))
        span.set_attribute("datasyn.response_locale", response_locale or "en")

        invoke_messages = build_agent_invoke_messages(history, message)
        logger.info(
            "[%s] chat_turn start message_chars=%s history_items=%s lc_messages=%s",
            rid,
            len(message),
            len(history or []),
            len(invoke_messages),
        )

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
        span.set_attribute("datasyn.mcp_tool_count", len(tool_names))

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
                response_locale=loc,
                feature="agent-chat",
                endpoint="api-agent-chat",
            )
            invoke_config["run_name"] = "datasyn-agent-chat"
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
                                {"messages": invoke_messages},
                                config=invoke_config,
                                request_id=rid,
                            )
                        reply = resolve_assistant_reply(state)
                        finalize_root_observation(root_obs, reply=reply)
                else:
                    state = await _ainvoke_with_empty_generation_retry(
                        agent,
                        {"messages": invoke_messages},
                        config=invoke_config,
                        request_id=rid,
                    )
                    reply = resolve_assistant_reply(state)
        finally:
            flush_langfuse()

        invoke_ms = round((time.perf_counter() - t_invoke) * 1000, 2)
        logger.info("[%s] agent.ainvoke finished ms=%s state_keys=%s", rid, invoke_ms, list(state.keys()))
        record("agent_ainvoke", ms=invoke_ms)
        span.set_attribute("datasyn.invoke_ms", invoke_ms)

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
        span.set_attribute("datasyn.total_ms", total_ms)
        span.set_attribute("datasyn.reply_chars", len(reply))

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
                    "every subdir with a SKILL.md). Subagents: `task(subagent_type=\"query\"|\"data-analyst\"|\"general-purpose\")`; "
                    "`query` is default per user turn (full MCP, compact return). `data-analyst` uses DuckDB+Dagster MCP only. Sandbox virtual path: `/sandbox/`."
                ),
                "steps": steps,
            }

        return ChatTurnResult(reply=reply, request_id=rid, debug=debug)


_STREAM_MODES = ["messages", "updates", "values"]


async def stream_agent_chat_sse_events(
    message: str,
    *,
    history: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
    langfuse_session_id: str | None = None,
    langfuse_user_id: str | None = None,
    response_locale: str = "en",
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON-serializable event dicts for SSE (start → stream → done | error).

    Uses LangGraph v2 streaming with ``subgraphs=True`` so subagent ``task`` runs surface
    under separate namespaces (see Deep Agents streaming docs).
    """
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
        logger.info("[%s] stream %s %s", rid, step, extra)

    with tracer.start_as_current_span("brain.stream_agent_chat_sse_events") as span:
        span.set_attribute("datasyn.request_id", rid)
        span.set_attribute("datasyn.message_chars", len(message))
        span.set_attribute("datasyn.history_turns", len(history or []))

        invoke_messages = build_agent_invoke_messages(history, message)

        yield {"event": "start", "request_id": rid}

        connections = _tool_connections()
        record("mcp_config_loaded", servers=list(connections.keys()))

        client = MultiServerToolClient(connections, tool_name_prefix=True)
        with tracer.start_as_current_span("brain.mcp_get_tools_stream"):
            tools = await client.get_tools()
        tool_names = sorted([getattr(t, "name", repr(t)) for t in tools])
        record("mcp_get_tools", tool_count=len(tools), tool_names=tool_names)

        loc = "es" if (response_locale or "en").strip().lower() == "es" else "en"
        agent = build_agent(tools, response_locale=loc)

        lf_handler = create_langchain_callback_handler()
        callbacks: list[Any] = [MCPToolResponseLogger(rid)]
        invoke_config: dict[str, Any] = {"callbacks": callbacks}
        if lf_handler:
            callbacks.append(lf_handler)
            invoke_config["metadata"] = build_langfuse_run_metadata(
                request_id=rid,
                session_id=langfuse_session_id,
                user_id=langfuse_user_id,
                response_locale=loc,
                feature="agent-chat-stream",
                endpoint="api-agent-chat-stream",
            )
            invoke_config["run_name"] = "datasyn-agent-chat-stream"

        payload = {"messages": invoke_messages}
        last_root_state: dict[str, Any] | None = None
        main_acc: list[str] = []
        sub_acc: list[str] = []

        t_invoke = time.perf_counter()
        reply = ""
        stream_error: Exception | None = None
        try:
            if lf_handler:
                from langfuse import propagate_attributes

                with root_chat_observation(request_id=rid, user_message=message) as root_obs:
                    with propagate_attributes(
                        session_id=langfuse_session_id,
                        user_id=langfuse_user_id,
                    ):
                        async for part in agent.astream(
                            payload,
                            config=invoke_config,
                            stream_mode=_STREAM_MODES,
                            subgraphs=True,
                            version="v2",
                        ):
                            if not isinstance(part, dict):
                                continue
                            if part.get("type") == "values" and not part.get("ns"):
                                data = part.get("data")
                                if isinstance(data, dict):
                                    last_root_state = data
                            for evt in langgraph_stream_part_to_events(part):
                                if evt.get("event") == "token":
                                    if evt.get("source") == "main":
                                        main_acc.append(evt.get("text") or "")
                                    else:
                                        sub_acc.append(evt.get("text") or "")
                                yield evt
                        reply = (
                            resolve_assistant_reply(last_root_state)
                            if last_root_state is not None
                            else ""
                        )
                        if not (reply or "").strip():
                            reply = "".join(main_acc)
                        finalize_root_observation(root_obs, reply=reply)
            else:
                async for part in agent.astream(
                    payload,
                    config=invoke_config,
                    stream_mode=_STREAM_MODES,
                    subgraphs=True,
                    version="v2",
                ):
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "values" and not part.get("ns"):
                        data = part.get("data")
                        if isinstance(data, dict):
                            last_root_state = data
                    for evt in langgraph_stream_part_to_events(part):
                        if evt.get("event") == "token":
                            if evt.get("source") == "main":
                                main_acc.append(evt.get("text") or "")
                            else:
                                sub_acc.append(evt.get("text") or "")
                        yield evt
                reply = (
                    resolve_assistant_reply(last_root_state) if last_root_state is not None else ""
                )
                if not (reply or "").strip():
                    reply = "".join(main_acc)
        except Exception as exc:
            stream_error = exc
            logger.exception("[%s] agent stream failed", rid)
            yield {"event": "error", "message": str(exc).strip()[:2000], "request_id": rid}
        finally:
            flush_langfuse()

        if stream_error is not None:
            return

        invoke_ms = round((time.perf_counter() - t_invoke) * 1000, 2)
        record("agent_astream", ms=invoke_ms)
        total_ms = round((time.perf_counter() - t0) * 1000, 2)

        msg_summary = summarize_messages_for_debug(last_root_state or {})
        debug: dict[str, Any] | None = None
        if settings.pipeline_debug:
            debug = {
                "request_id": rid,
                "total_ms": total_ms,
                "invoke_ms": invoke_ms,
                "tool_names": tool_names,
                "messages": msg_summary,
                "steps": steps,
            }

        yield {
            "event": "done",
            "reply": reply,
            "subagent_reply": "".join(sub_acc),
            "request_id": rid,
            "debug": debug,
        }
