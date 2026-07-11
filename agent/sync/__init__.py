"""Quack protocol sync: external DuckDB → main warehouse via MCP."""

from agent.sync.quack_sync import (
    bootstrap_sync_registry,
    build_lineage_ui_resource,
    load_sync_sources,
    run_quack_sync,
    sync_status,
)

__all__ = [
    "bootstrap_sync_registry",
    "build_lineage_ui_resource",
    "load_sync_sources",
    "run_quack_sync",
    "sync_status",
]
