"""Runtime chat model override (session-scoped; does not mutate ``.env``)."""

from __future__ import annotations

import threading

from agent.config import settings

_lock = threading.Lock()
_runtime_chat_model: str | None = None


def effective_chat_model() -> str | None:
    """Active model id: runtime override if set, else ``CHAT_MODEL`` from env."""
    with _lock:
        if _runtime_chat_model:
            return _runtime_chat_model
    env = (settings.chat_model or "").strip()
    return env or None


def chat_model_source() -> str:
    """``runtime`` when the UI or API set an override; otherwise ``env``."""
    with _lock:
        if _runtime_chat_model:
            return "runtime"
    return "env"


def set_runtime_chat_model(model_id: str | None) -> str | None:
    """Set or clear the runtime override. Returns the new effective model id."""
    global _runtime_chat_model
    cleaned = (model_id or "").strip() or None
    with _lock:
        _runtime_chat_model = cleaned
    return effective_chat_model()
