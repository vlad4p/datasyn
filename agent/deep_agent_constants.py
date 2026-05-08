"""Shared strings for deep-agent wiring (avoids import cycles with ``load_prompt``)."""

# Ephemeral virtual path routed to ``StateBackend`` in ``CompositeBackend``.
SANDBOX_PREFIX = "/sandbox/"

# ``task`` tool: ``subagent_type="data-analyst"`` (DuckDB + Dagster MCP only).
DATA_ANALYST_SUBAGENT_TYPE = "data-analyst"
