"""Build LangChain message lists for multi-turn chat (Deep Agent state ``messages``)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

# Hard cap on LangChain messages per invoke (after merge with the new user turn).
_DEFAULT_MAX_MESSAGES = 200


def _trim_starting_at_human(msgs: list[BaseMessage]) -> list[BaseMessage]:
    """Drop leading non-human messages (invalid partial window after trimming)."""
    i = 0
    while i < len(msgs) and type(msgs[i]).__name__ != "HumanMessage":
        i += 1
    return msgs[i:]


def trim_messages_to_max(msgs: list[BaseMessage], max_messages: int) -> list[BaseMessage]:
    """Keep at most ``max_messages`` from the end; ensure the window starts with HumanMessage."""
    if max_messages < 1 or len(msgs) <= max_messages:
        return msgs
    return _trim_starting_at_human(msgs[-max_messages:])


def history_dicts_to_messages(history: list[dict[str, Any]] | None) -> list[BaseMessage]:
    """Convert API/UI history items to LangChain messages (no new user turn)."""
    out: list[BaseMessage] = []
    if not history:
        return out
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        raw = item.get("content")
        content = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def build_agent_invoke_messages(
    history: list[dict[str, Any]] | None,
    new_user_message: str,
    *,
    max_messages: int = _DEFAULT_MAX_MESSAGES,
) -> list[BaseMessage]:
    """Prior turns + ``HumanMessage(new_user_message)``, trimmed to ``max_messages``."""
    msgs = history_dicts_to_messages(history)
    msgs.append(HumanMessage(content=new_user_message))
    return trim_messages_to_max(msgs, max_messages)
