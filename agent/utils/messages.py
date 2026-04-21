"""Helpers for reading Deep Agent / LangGraph state messages."""

from __future__ import annotations

from typing import Any


def _content_to_str(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p).strip()
    if content is None:
        return ""
    return str(content).strip()


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


def resolve_assistant_reply(state: dict[str, Any]) -> str:
    """Prefer the final assistant text; if empty (e.g. last msg is ToolMessage), walk back for AIMessage."""
    messages: list[Any] = state.get("messages") or []
    if not messages:
        return str(state)

    def text_from(msg: Any) -> str:
        return _content_to_str(getattr(msg, "content", None))

    primary = last_assistant_text(state)
    if primary.strip():
        return primary

    for msg in reversed(messages):
        name = type(msg).__name__
        if name in ("AIMessage", "AIMessageChunk"):
            t = text_from(msg)
            if t.strip():
                return t
    return primary


def summarize_messages_for_debug(state: dict[str, Any]) -> dict[str, Any]:
    """Structured timeline for logs / optional API debug (no full tool payloads)."""
    messages: list[Any] = state.get("messages") or []
    timeline: list[dict[str, Any]] = []
    for i, m in enumerate(messages):
        name = type(m).__name__
        row: dict[str, Any] = {"idx": i, "type": name}
        if name in ("AIMessage", "AIMessageChunk"):
            tcs = getattr(m, "tool_calls", None) or []
            if tcs:
                names: list[str] = []
                for tc in tcs:
                    if isinstance(tc, dict):
                        names.append(str(tc.get("name", "?")))
                    else:
                        names.append(str(getattr(tc, "name", "?")))
                row["tool_calls"] = names
        if name == "ToolMessage":
            row["name"] = getattr(m, "name", None)
            c = str(getattr(m, "content", ""))
            row["content_chars"] = len(c)
            row["content_preview"] = c[:400] + ("…" if len(c) > 400 else "")
        timeline.append(row)
    return {"message_count": len(messages), "timeline": timeline}
