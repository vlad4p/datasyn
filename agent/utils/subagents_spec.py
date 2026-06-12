"""Declarative subagents and composite sandbox backend for ``create_deep_agent``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from deepagents import FilesystemPermission
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.deep_agent_constants import (
    DATA_ANALYST_SUBAGENT_TYPE,
    QUERY_SUBAGENT_TYPE,
    SANDBOX_PREFIX,
)
from agent.skills import skills_virtual_dir
from agent.utils.load_prompt import warehouse_subagent_system_prompt

logger = logging.getLogger(__name__)

# User-facing deliverables (same root as the main agent).
REPORTS_GLOB = "/reports/**"

_SUBAGENT_WRITE_PERMS: list[FilesystemPermission] = [
    FilesystemPermission(operations=["write"], paths=[SANDBOX_PREFIX + "**", REPORTS_GLOB], mode="allow"),
    FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
]


def build_composite_backend(*, project_root: Path, skills_root: Path | None = None) -> CompositeBackend:
    """Project files on disk + skills route + ephemeral ``/sandbox/`` (state-only)."""
    root = str(project_root.resolve())
    skills_dir = str((skills_root or project_root / "skills").resolve())
    return CompositeBackend(
        default=FilesystemBackend(root_dir=root, virtual_mode=True),
        routes={
            SANDBOX_PREFIX: StateBackend(),
            "/skills/": FilesystemBackend(root_dir=skills_dir, virtual_mode=True),
        },
    )


def mcp_tools_duckdb_dagster(tools: list[BaseTool]) -> list[BaseTool]:
    """DuckDB + Dagster MCP tools only (names prefixed by ``mcp.json`` server keys)."""
    out: list[BaseTool] = []
    for t in tools:
        name = str(getattr(t, "name", "") or "")
        if name.startswith("duckdb_") or name.startswith("dagster_"):
            out.append(t)
    if not out:
        logger.warning(
            "No duckdb_ or dagster_ tools in MCP tool list; data-analyst subagent will have "
            "filesystem helpers only. Check mcp.json and that duckdb-mcp / dagster-mcp are up."
        )
    return out


def _mcp_tool_names(tools: list[BaseTool]) -> list[str]:
    return sorted(str(getattr(t, "name", "") or "") for t in tools if getattr(t, "name", None))


def disabled_general_purpose_subagent() -> dict[str, Any]:
    """Override Deep Agents default ``general-purpose`` subagent (no MCP tools)."""
    return {
        "name": "general-purpose",
        "description": (
            "Disabled in Datasyn. Do **not** use. Always delegate with "
            f"`task(subagent_type=\"{QUERY_SUBAGENT_TYPE}\")` or `{DATA_ANALYST_SUBAGENT_TYPE}`."
        ),
        "system_prompt": (
            "This subagent is disabled. Return immediately that the parent must use "
            f"`{QUERY_SUBAGENT_TYPE}` instead."
        ),
        "tools": [],
    }


def query_subagent(
    *,
    tools: list[BaseTool],
    model: BaseChatModel | None = None,
    response_locale: str = "en",
) -> dict[str, Any]:
    """``SubAgent`` spec: per-turn information gathering with full MCP tools; compact return."""
    spec: dict[str, Any] = {
        "name": QUERY_SUBAGENT_TYPE,
        "description": (
            "Default subagent for **every user query**: runs MCP tools and skills to collect **precise facts** "
            "(schema, SQL results, catalog metadata, file paths, counts, markdown tables) and returns a **short structured "
            "brief**—not raw tool dumps. Use for all substantive questions so the main orchestrator thread stays small. "
            "Has the full MCP tool set. Write scratch under `/sandbox/`; reports under `/reports/`."
        ),
        "system_prompt": warehouse_subagent_system_prompt(
            "query_subagent.txt",
            mcp_tool_names=_mcp_tool_names(tools),
            response_locale=response_locale,
            extra_playbooks=["query_news_political_playbook.txt"],
        ),
        "tools": tools,
        "skills": [skills_virtual_dir()],
        "permissions": _SUBAGENT_WRITE_PERMS,
    }
    if model is not None:
        spec["model"] = model
    return spec


def data_analyst_subagent(
    *,
    tools: list[BaseTool],
    model: BaseChatModel | None = None,
    response_locale: str = "en",
) -> dict[str, Any]:
    """``SubAgent`` spec: warehouse SQL, catalog SQL, Dagster project ops, sandbox scratch files."""
    duckdb_tools = mcp_tools_duckdb_dagster(tools)
    spec: dict[str, Any] = {
        "name": DATA_ANALYST_SUBAGENT_TYPE,
        "description": (
            "Dedicated data-warehouse analyst: runs DuckDB SQL, explores schemas, lists `/data-local` via "
            "duckdb tools, and uses Dagster MCP for code locations, jobs, deploy, and **dagster_catalog_*** "
            "metadata when configured. Use for heavy or isolated analysis, multi-step SQL, or pipeline/catalog "
            "work so the main thread stays small. **Does not** include `storage_*` MinIO tools—delegate "
            "object listing to the main agent. Write scratch work under `/sandbox/`; put user-facing reports under "
            "`/reports/` (or the configured reports path)."
        ),
        "system_prompt": warehouse_subagent_system_prompt(
            "data_analyst_subagent.txt",
            mcp_tool_names=_mcp_tool_names(duckdb_tools),
            response_locale=response_locale,
        ),
        "tools": duckdb_tools,
        "skills": [skills_virtual_dir()],
        "permissions": _SUBAGENT_WRITE_PERMS,
    }
    if model is not None:
        spec["model"] = model
    return spec
