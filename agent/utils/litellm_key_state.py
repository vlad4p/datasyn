"""Runtime LiteLLM virtual key override (session-scoped; does not mutate ``.env``)."""

from __future__ import annotations

import threading

from agent.config import settings

_lock = threading.Lock()
_runtime_litellm_key: str | None = None


def effective_litellm_key() -> str | None:
    """Active key: runtime override if set, else ``LITELLM_KEY`` / aliases from env."""
    with _lock:
        if _runtime_litellm_key:
            return _runtime_litellm_key
    return settings.litellm_key


def litellm_key_source() -> str:
    """``runtime`` when the UI or API set an override; otherwise ``env``."""
    with _lock:
        if _runtime_litellm_key:
            return "runtime"
    return "env"


def set_runtime_litellm_key(key: str | None) -> str | None:
    """Set or clear the runtime override. Returns the new effective key (or None)."""
    global _runtime_litellm_key
    cleaned = (key or "").strip() or None
    with _lock:
        _runtime_litellm_key = cleaned
    return effective_litellm_key()
