"""One-turn chat: load remote HTTP tool servers and run the Deep Agent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient

from agent.graph import build_agent
from agent.utils.messages import last_assistant_text
from agent.config import settings


def _project_root() -> Path:
    return settings.project_root


def _tool_connections() -> dict[str, Any]:
    """HTTP connection map (env overrides, then ``tool_servers.json``)."""
    defaults = {
        "catalog": "http://127.0.0.1:8010/mcp",
        "database": "http://127.0.0.1:8030/mcp",
        "process": "http://127.0.0.1:8020/mcp",
    }
    env_keys = {
        "catalog": "TOOL_CATALOG_URL",
        "database": "TOOL_DATABASE_URL",
        "process": "TOOL_PROCESS_URL",
    }
    file_urls: dict[str, str] = {}
    cfg_path = _project_root() / "tool_servers.json"
    if cfg_path.is_file():
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        servers = raw.get("servers", {})
        for name, spec in servers.items():
            if isinstance(spec, dict) and spec.get("url"):
                file_urls[str(name)] = str(spec["url"])

    connections: dict[str, Any] = {}
    for name, default_url in defaults.items():
        url = os.environ.get(env_keys[name]) or file_urls.get(name) or default_url
        connections[name] = {"transport": "http", "url": url}
    return connections


async def run_agent_chat_turn(message: str) -> str:
    client = MultiServerToolClient(_tool_connections(), tool_name_prefix=True)
    tools = await client.get_tools()
    agent = build_agent(tools)
    state = await agent.ainvoke({"messages": [HumanMessage(content=message)]})
    return last_assistant_text(state)
