"""Optional Langfuse tracing for LangChain / LangGraph (env-gated).

Requires ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY``. Set ``LANGFUSE_BASE_URL`` for
self-hosted or US cloud (see https://langfuse.com/docs/observability/sdk/overview).

Import this module only after application env is loaded (e.g. after ``agent.config``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Preview caps avoid dumping huge prompts / replies into Langfuse by default.
_TRACE_INPUT_MAX = 4000
_TRACE_OUTPUT_MAX = 8000


def langfuse_tracing_enabled() -> bool:
    pub = (os.environ.get("LANGFUSE_PUBLIC_KEY") or "").strip()
    sec = (os.environ.get("LANGFUSE_SECRET_KEY") or "").strip()
    return bool(pub and sec)


def _running_in_docker() -> bool:
    return os.path.exists("/.dockerenv")


def log_langfuse_docker_loopback_hint() -> None:
    """If Langfuse host is loopback while the brain runs in Docker, OTLP export hits the container, not the host."""
    if not langfuse_tracing_enabled():
        return
    base = (
        os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or ""
    ).strip()
    if not base:
        return
    lower = base.lower()
    if _running_in_docker() and ("localhost" in lower or "127.0.0.1" in lower):
        import logging

        logging.getLogger(__name__).warning(
            "Langfuse is configured with a loopback URL (%r) but the brain runs in Docker — "
            "OpenTelemetry export will target this container, not your host. "
            "Set LANGFUSE_BASE_URL to a reachable host (e.g. http://host.docker.internal:3000 for Langfuse on the host, "
            "or https://cloud.langfuse.com). docker-compose already maps host.docker.internal for the brain.",
            base,
        )


def flush_langfuse() -> None:
    """Best practice: flush buffered spans before process exit or after a request in short-lived workers."""
    if not langfuse_tracing_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        pass


def create_langchain_callback_handler() -> Any | None:
    """Return a Langfuse ``CallbackHandler`` for ``config['callbacks']``, or ``None`` if disabled."""
    if not langfuse_tracing_enabled():
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def _preview(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


@contextmanager
def root_chat_observation(
    *,
    request_id: str,
    user_message: str,
) -> Iterator[Any]:
    """Root span + deterministic trace id (seed = request id) for distributed correlation."""
    if not langfuse_tracing_enabled():
        yield None
        return

    from langfuse import Langfuse, get_client

    lf = get_client()
    trace_id = Langfuse.create_trace_id(seed=request_id)
    with lf.start_as_current_observation(
        as_type="span",
        name="datacyber-agent-chat",
        trace_context={"trace_id": trace_id},
    ) as obs:
        obs.set_trace_io(
            input={"user_message": _preview(user_message, _TRACE_INPUT_MAX)},
        )
        try:
            yield obs
        finally:
            pass


def finalize_root_observation(obs: Any | None, *, reply: str) -> None:
    if obs is None:
        return
    try:
        obs.set_trace_io(
            output={"assistant_reply": _preview(reply, _TRACE_OUTPUT_MAX)},
        )
    except Exception:
        pass


def build_langfuse_run_metadata(
    *,
    request_id: str,
    session_id: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    """LangChain config metadata keys consumed by Langfuse (see Langfuse LangChain docs)."""
    meta: dict[str, Any] = {
        "langfuse_tags": ["datacyber-brain", "agent-chat"],
    }
    if session_id:
        meta["langfuse_session_id"] = session_id
    if user_id:
        meta["langfuse_user_id"] = user_id
    return meta
