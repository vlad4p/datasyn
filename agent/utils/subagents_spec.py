"""Declarative subagents and composite sandbox backend for ``create_deep_agent``."""

from __future__ import annotations

import logging
from pathlib import Path

from deepagents import FilesystemPermission
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain_core.tools import BaseTool

from agent.deep_agent_constants import DATA_ANALYST_SUBAGENT_TYPE, SANDBOX_PREFIX
from agent.utils.load_prompt import load_prompt

logger = logging.getLogger(__name__)

# User-facing deliverables (same root as the main agent).
REPORTS_GLOB = "/reports/**"

_DATA_ANALYST_WRITE_PERMS: list[FilesystemPermission] = [
    FilesystemPermission(operations=["write"], paths=[SANDBOX_PREFIX + "**", REPORTS_GLOB], mode="allow"),
    FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
]


def build_composite_backend(*, project_root: Path) -> CompositeBackend:
    """Project files on disk + ephemeral ``/sandbox/`` (state-only, not persisted to git)."""
    root = str(project_root.resolve())
    return CompositeBackend(
        default=FilesystemBackend(root_dir=root, virtual_mode=True),
        routes={SANDBOX_PREFIX: StateBackend()},
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


def data_analyst_subagent(*, tools: list[BaseTool]) -> dict:
    """``SubAgent`` spec: warehouse SQL, catalog SQL, Dagster project ops, sandbox scratch files."""
    return {
        "name": DATA_ANALYST_SUBAGENT_TYPE,
        "description": (
            "Dedicated data-warehouse analyst: runs DuckDB SQL, explores schemas, lists `/data-local` via "
            "duckdb tools, and uses Dagster MCP for code locations, jobs, deploy, and **dagster_catalog_*** "
            "metadata when configured. Use for heavy or isolated analysis, multi-step SQL, or pipeline/catalog "
            "work so the main thread stays small. **Does not** include scrapper or other MCP servers—delegate "
            "scraping to the main agent. Write scratch work under `/sandbox/`; put user-facing reports under "
            "`/reports/` (or the configured reports path)."
        ),
        "system_prompt": load_prompt("data_analyst_subagent.txt"),
        "tools": mcp_tools_duckdb_dagster(tools),
        "skills": ["/skills/"],
        "permissions": _DATA_ANALYST_WRITE_PERMS,
    }
