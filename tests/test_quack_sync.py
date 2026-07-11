"""Unit tests for Quack sync helpers (no live MCP)."""

from __future__ import annotations

from types import SimpleNamespace

from agent.sync.quack_sync import (
    _parse_pipe_table,
    _require_ident,
    _resolve_sql_arg_key,
    _sql_str,
)


def test_sql_str_escapes_quotes() -> None:
    assert _sql_str("a'b") == "'a''b'"


def test_require_ident_ok() -> None:
    assert _require_ident("bronze", label="schema") == "bronze"


def test_require_ident_rejects_bad() -> None:
    try:
        _require_ident("bad-name", label="schema")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_pipe_table() -> None:
    text = """
| table_schema | table_name |
|--------------|------------|
| bronze       | foo        |
| silver       | bar        |
"""
    rows = _parse_pipe_table(text)
    assert len(rows) == 2
    assert rows[0]["table_schema"] == "bronze"
    assert rows[0]["table_name"] == "foo"
    assert rows[1]["table_name"] == "bar"


def test_resolve_sql_arg_key_prefers_sql() -> None:
    tool = SimpleNamespace(args_schema={"properties": {"sql": {"type": "string"}}})
    assert _resolve_sql_arg_key(tool) == "sql"


def test_resolve_sql_arg_key_defaults_to_sql() -> None:
    tool = SimpleNamespace(args_schema=None)
    assert _resolve_sql_arg_key(tool) == "sql"


def test_resolve_sql_arg_key_accepts_query_alias() -> None:
    tool = SimpleNamespace(args={"properties": {"query": {"type": "string"}}})
    assert _resolve_sql_arg_key(tool) == "query"
