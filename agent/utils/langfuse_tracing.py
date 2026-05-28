"""Optional Langfuse tracing for LangChain / LangGraph (env-gated).

Requires ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY``. Set ``LANGFUSE_BASE_URL`` for
self-hosted or US cloud (see https://langfuse.com/docs/observability/sdk/overview).

Import this module only after application env is loaded (e.g. after ``agent.config``).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Preview caps avoid dumping huge prompts / replies into Langfuse by default.
_TRACE_INPUT_MAX = 4000
_TRACE_OUTPUT_MAX = 8000
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Common secret/key patterns we do not want in traces.
    (re.compile(r"\bsk-[A-Za-z0-9\-_]{12,}\b"), "[REDACTED_SK]"),
    (re.compile(r"\bpk-[A-Za-z0-9\-_]{12,}\b"), "[REDACTED_PK]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9\-_\.]{12,}\b", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[REDACTED_HEX]"),
)


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
    sanitized = _sanitize_text(text)
    if len(sanitized) <= max_len:
        return sanitized
    return sanitized[: max_len - 1] + "…"


def _sanitize_text(text: str) -> str:
    out = text
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    # Keep lightweight PII minimization for direct user identifiers in free text.
    out = re.sub(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        "[REDACTED_EMAIL]",
        out,
    )
    return out


def _safe_tag(tag: str) -> str:
    cleaned = re.sub(r"[^a-z0-9:_\-]+", "-", tag.strip().lower())
    cleaned = cleaned.strip("-")
    return cleaned[:80] if cleaned else "unknown"


def _dedupe_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _normalize_locale_tag(response_locale: str | None) -> str:
    loc = (response_locale or "en").strip().lower()
    return "locale:es" if loc == "es" else "locale:en"


def _normalize_feature_tag(feature: str | None) -> str:
    if not feature:
        return "feature:agent-chat"
    return f"feature:{_safe_tag(feature)}"


def _normalize_endpoint_tag(endpoint: str | None) -> str:
    if not endpoint:
        return "endpoint:agent-chat"
    return f"endpoint:{_safe_tag(endpoint)}"


def _normalize_env_tag(runtime_env: str | None) -> str:
    env = (runtime_env or os.environ.get("ENVIRONMENT") or "dev").strip().lower()
    return f"env:{_safe_tag(env)}"


def _normalize_release_tag(release: str | None) -> str | None:
    if not release:
        return None
    return f"release:{_safe_tag(release)}"


def _resolve_runtime_release() -> str | None:
    candidates = (
        os.environ.get("DATASYN_RELEASE"),
        os.environ.get("APP_VERSION"),
        os.environ.get("GIT_SHA"),
    )
    for item in candidates:
        if item and item.strip():
            return item.strip()
    return None


def _build_default_tags(
    *,
    response_locale: str | None,
    feature: str | None,
    endpoint: str | None,
    runtime_env: str | None,
) -> list[str]:
    tags = [
        "datasyn-brain",
        "agent-chat",
        _normalize_feature_tag(feature),
        _normalize_endpoint_tag(endpoint),
        _normalize_locale_tag(response_locale),
        _normalize_env_tag(runtime_env),
    ]
    release_tag = _normalize_release_tag(_resolve_runtime_release())
    if release_tag:
        tags.append(release_tag)
    return _dedupe_tags(tags)


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
        name="datasyn-agent-chat",
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
    response_locale: str | None = None,
    feature: str | None = None,
    endpoint: str | None = None,
    runtime_env: str | None = None,
) -> dict[str, Any]:
    """LangChain config metadata keys consumed by Langfuse (see Langfuse LangChain docs)."""
    meta: dict[str, Any] = {
        "langfuse_tags": _build_default_tags(
            response_locale=response_locale,
            feature=feature,
            endpoint=endpoint,
            runtime_env=runtime_env,
        ),
    }
    if session_id:
        meta["langfuse_session_id"] = session_id
    if user_id:
        meta["langfuse_user_id"] = user_id
    # Helpful join key for external logs while avoiding sensitive payload fields.
    meta["datasyn_request_id"] = request_id
    return meta
