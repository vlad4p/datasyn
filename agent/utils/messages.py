"""Helpers for reading Deep Agent / LangGraph state messages."""

from __future__ import annotations

from typing import Any


def last_assistant_text(state: dict[str, Any]) -> str:
    """Return the last message content as plain text (handles multimodal blocks)."""
    messages = state.get("messages", [])
    if not messages:
        return str(state)
    last = messages[-1]
    content = getattr(last, "content", str(last))
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p).strip() or str(content)
    return str(content)
