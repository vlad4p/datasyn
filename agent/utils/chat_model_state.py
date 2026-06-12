"""Runtime chat model override (session-scoped; does not mutate ``.env``)."""

from __future__ import annotations

import logging
import threading

from agent.config import settings
from agent.utils.openrouter_free_defaults import (
    OPENROUTER_FREE_FAST_MODEL,
    OPENROUTER_FREE_ORCHESTRATOR_MODEL,
    warn_if_slow_free_model,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_runtime_chat_model: str | None = None
_warned_slow_fast: set[str] = set()


def _openrouter_free_default(*, tier: str) -> str | None:
    if settings.model_provider != "openrouter":
        return None
    if tier == "fast":
        return OPENROUTER_FREE_FAST_MODEL
    return OPENROUTER_FREE_ORCHESTRATOR_MODEL


def effective_chat_model() -> str | None:
    """Active model id: runtime override if set, else ``CHAT_MODEL`` from env."""
    with _lock:
        if _runtime_chat_model:
            return _runtime_chat_model
    env = (settings.chat_model or "").strip()
    if env:
        return env
    return _openrouter_free_default(tier="default")


def effective_fast_chat_model() -> str | None:
    """Fast tier for subagents: ``CHAT_MODEL_FAST``, else orchestrator model / OpenRouter free default."""
    fast = (settings.chat_model_fast or "").strip()
    if fast:
        resolved = fast
    else:
        resolved = _openrouter_free_default(tier="fast") or effective_chat_model()
    if resolved:
        msg = warn_if_slow_free_model(resolved, tier="fast")
        if msg and resolved not in _warned_slow_fast:
            _warned_slow_fast.add(resolved)
            logger.warning(msg)
    return resolved


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
