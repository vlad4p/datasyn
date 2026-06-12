"""Tests for orchestrator delegation, locale, and prompt split."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage

from agent.middleware.orchestrator_tools import OrchestratorMcpGuardMiddleware, is_mcp_tool_name
from agent.utils.locale_detect import message_looks_spanish, resolve_response_locale
from agent.utils.load_prompt import orchestrator_system_prompt, warehouse_subagent_system_prompt
from agent.utils.openrouter_free_defaults import (
    OPENROUTER_FREE_FAST_MODEL,
    OPENROUTER_FREE_ORCHESTRATOR_MODEL,
    warn_if_slow_free_model,
)


def test_is_mcp_tool_name() -> None:
    assert is_mcp_tool_name("duckdb_get_schema")
    assert is_mcp_tool_name("dagster_list_projects")
    assert is_mcp_tool_name("storage_list_buckets")
    assert not is_mcp_tool_name("task")
    assert not is_mcp_tool_name("read_file")


def test_orchestrator_middleware_blocks_mcp_tool_call() -> None:
    mw = OrchestratorMcpGuardMiddleware()
    request = MagicMock()
    request.tool_call = {"name": "duckdb_get_schema", "id": "call-1"}
    result = mw.wrap_tool_call(request, MagicMock())
    assert isinstance(result, ToolMessage)
    assert "blocked on orchestrator" in result.content
    assert result.tool_call_id == "call-1"


def test_resolve_response_locale_spanish_message() -> None:
    assert resolve_response_locale("Dame un listado de las tablas", "en") == "es"
    assert resolve_response_locale("List all tables", "en") == "en"
    assert resolve_response_locale("anything", "es") == "es"


def test_message_looks_spanish() -> None:
    assert message_looks_spanish("Dame un listado")
    assert not message_looks_spanish("List all tables please")


def test_orchestrator_prompt_smaller_than_warehouse_subagent() -> None:
    tools = ["duckdb_get_schema", "duckdb_execute_query", "storage_list_buckets"]
    orch = orchestrator_system_prompt(mcp_tool_names=tools, response_locale="en")
    sub = warehouse_subagent_system_prompt(
        "query_subagent.txt",
        mcp_tool_names=tools,
        response_locale="en",
        extra_playbooks=["query_news_political_playbook.txt"],
    )
    assert len(orch) < len(sub)
    assert len(orch) < 20_000
    assert "query subagent" in sub.lower()
    assert "resume / edita" in orch.lower() or "resume/edita" in orch.lower()


def test_compact_subagent_prompt_much_smaller_than_full_agents_md() -> None:
    tools = ["duckdb_get_schema"]
    compact = warehouse_subagent_system_prompt(
        "query_subagent.txt",
        mcp_tool_names=tools,
        response_locale="en",
    )
    prev = os.environ.get("DATASYN_SUBAGENT_FULL_AGENTS_MD")
    os.environ["DATASYN_SUBAGENT_FULL_AGENTS_MD"] = "1"
    try:
        full = warehouse_subagent_system_prompt(
            "query_subagent.txt",
            mcp_tool_names=tools,
            response_locale="en",
        )
    finally:
        if prev is None:
            os.environ.pop("DATASYN_SUBAGENT_FULL_AGENTS_MD", None)
        else:
            os.environ["DATASYN_SUBAGENT_FULL_AGENTS_MD"] = prev
    assert len(compact) < len(full) * 0.5
    assert "warehouse subagent playbook" in compact.lower()


def test_query_subagent_includes_news_political_playbook() -> None:
    tools = ["duckdb_execute_query"]
    sub = warehouse_subagent_system_prompt(
        "query_subagent.txt",
        mcp_tool_names=tools,
        response_locale="es",
        extra_playbooks=["query_news_political_playbook.txt"],
    )
    assert "sentiment-analysis" in sub
    assert "reporte político" in sub.lower() or "reporte politico" in sub.lower()


def test_warn_slow_free_model_for_fast_tier() -> None:
    msg = warn_if_slow_free_model("nvidia/nemotron-3-super-120b-a12b:free", tier="fast")
    assert msg is not None
    assert OPENROUTER_FREE_FAST_MODEL in msg
    assert warn_if_slow_free_model(OPENROUTER_FREE_ORCHESTRATOR_MODEL, tier="fast") is None


def test_openrouter_free_default_constants() -> None:
    assert OPENROUTER_FREE_FAST_MODEL.endswith(":free")
    assert OPENROUTER_FREE_ORCHESTRATOR_MODEL.endswith(":free")
