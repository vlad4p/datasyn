"""Map LangGraph v2 ``astream`` parts (Deep Agents / subgraphs) to UI-safe SSE payloads.

See https://docs.langchain.com/oss/python/deepagents/streaming — ``version=\"v2\"``,
``subgraphs=True``, ``stream_mode`` includes ``messages`` / ``updates`` / ``values``.
"""

from __future__ import annotations

from typing import Any


def _ns_list(ns: Any) -> list[str]:
    if ns is None:
        return []
    if isinstance(ns, tuple):
        return [str(x) for x in ns]
    return [str(ns)]


def _is_subagent_ns(ns: list[str]) -> bool:
    return any(s.startswith("tools:") for s in ns)


def _text_from_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def langgraph_stream_part_to_events(part: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one v2 ``StreamPart`` dict into zero or more JSON-serializable client events."""
    typ = part.get("type")
    ns = _ns_list(part.get("ns"))
    source: Any = "subagent" if _is_subagent_ns(ns) else "main"

    if typ == "messages":
        data = part.get("data")
        if not isinstance(data, tuple) or len(data) < 2:
            return []
        msg, _meta = data[0], data[1]
        out: list[dict[str, Any]] = []

        text = _text_from_message_content(getattr(msg, "content", None))
        if text:
            out.append(
                {
                    "event": "token",
                    "source": source,
                    "ns": ns,
                    "text": text,
                }
            )

        for tc in getattr(msg, "tool_call_chunks", None) or []:
            if not isinstance(tc, dict):
                continue
            name = tc.get("name")
            args = tc.get("args")
            if name or args:
                out.append(
                    {
                        "event": "tool_delta",
                        "source": source,
                        "ns": ns,
                        "tool_name": name,
                        "args_fragment": args if isinstance(args, str) else "",
                    }
                )
        return out

    if typ == "updates":
        data = part.get("data")
        if not isinstance(data, dict):
            return []
        events: list[dict[str, Any]] = []
        for node_name in data.keys():
            if str(node_name).startswith("__"):
                continue
            events.append(
                {
                    "event": "step",
                    "source": source,
                    "ns": ns,
                    "node": str(node_name),
                }
            )
        return events

    # values / custom / others — handled by caller (values used for final state)
    return []
