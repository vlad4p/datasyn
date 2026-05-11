"""Lightweight SQL policy for dagster-mcp ``catalog_execute_query``.

Only **one** statement per call, and the leading keyword must be one of:

- ``SELECT`` (optionally ``WITH … SELECT``)
- ``INSERT`` / ``UPDATE`` / ``DELETE`` (``RETURNING`` is fine)

DDL and privilege statements are rejected (same rules as the former catalog-mcp).
"""

from __future__ import annotations

import re

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING = re.compile(r"'(?:''|[^'])*'")

_ALLOWED_FIRST_TOKEN = {"select", "with", "insert", "update", "delete"}


def _strip_literals_and_comments(sql: str) -> str:
    text = _BLOCK_COMMENT.sub(" ", sql)
    text = _LINE_COMMENT.sub(" ", text)
    text = _STRING.sub("''", text)
    return text


def _first_token(text: str) -> str:
    parts = text.strip().split(None, 1)
    return parts[0].lower() if parts else ""


def validate_catalog_sql(sql: str) -> str | None:
    """Return an error string if *sql* violates the policy, else ``None``."""

    raw = (sql or "").strip()
    if not raw:
        return "empty SQL"
    if len(raw) > 200_000:
        return "SQL too long (> 200000 chars)"

    scrubbed = _strip_literals_and_comments(raw).strip().rstrip(";").strip()
    if not scrubbed:
        return "empty SQL after removing comments"

    if ";" in scrubbed:
        return "multiple statements are not allowed (single SELECT/INSERT/UPDATE/DELETE only)"

    first = _first_token(scrubbed)
    if first not in _ALLOWED_FIRST_TOKEN:
        return (
            f"only SELECT / WITH / INSERT / UPDATE / DELETE are allowed "
            f"(got {first!r}); DDL must go through catalog/migrations/"
        )
    return None
