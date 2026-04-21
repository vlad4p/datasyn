"""LiteLLM proxy chat - OpenAI-compatible client (same pattern as Ubika-core ``litellm_client.get_chat_model``).

Uses ``langchain_openai.ChatOpenAI`` with ``base_url`` = proxy (e.g. ``http://host:4000/v1``), not
``ChatLiteLLM``, so traffic goes to your LiteLLM instance instead of ``api.openai.com``.

Model ids must match your LiteLLM proxy (e.g. ``local/gemini-2.5-flash-lite`` from ``GET /v1/models``).

**Env (Ubika-compatible aliases supported):**

- Key: ``LITELLM_KEY`` or ``LITELLM_PROXY_KEY``
- Base: ``LITELLM_API_BASE`` or ``LITELLM_PROXY_BASE`` or ``LITELLM_URL`` (must include ``/v1``)
- Optional: ``LITELLM_REQUEST_TIMEOUT``, ``LITELLM_TEMPERATURE``
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agent.config import settings

logger = logging.getLogger(__name__)


def running_in_docker() -> bool:
    return os.path.exists("/.dockerenv")


async def probe_litellm_proxy() -> dict[str, Any]:
    """GET OpenAI-compatible ``/v1/models``; use ``GET /health/llm`` to debug connection from this process."""
    base = settings.litellm_api_base
    key = settings.litellm_key
    out: dict[str, Any] = {
        "in_docker": running_in_docker(),
        "litellm_base": base,
        "has_key": bool(key),
    }
    if not base or not key:
        out["ok"] = False
        out["error"] = "Set LITELLM_PROXY_BASE (or LITELLM_API_BASE) and LITELLM_KEY (or LITELLM_PROXY_KEY)."
        return out
    url = f"{base.rstrip('/')}/models"
    try:
        t = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=t, trust_env=False) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        out["status_code"] = r.status_code
        out["ok"] = 200 <= r.status_code < 300
        if not out["ok"]:
            out["body_preview"] = (r.text or "")[:400]
    except Exception as exc:
        out["ok"] = False
        out["error"] = str(exc)[:500]
    return out


def _request_timeout() -> float:
    raw = os.getenv("LITELLM_REQUEST_TIMEOUT", "300")
    try:
        return float(raw)
    except ValueError:
        return 300.0


def _temperature() -> float:
    raw = os.getenv("LITELLM_TEMPERATURE", "0.2")
    try:
        return float(raw)
    except ValueError:
        return 0.2


def build_chat_model() -> BaseChatModel:
    """Return a LangChain chat model that talks only to the LiteLLM OpenAI-compatible proxy."""
    if not settings.litellm_key:
        raise RuntimeError(
            "Set LITELLM_KEY or LITELLM_PROXY_KEY to your LiteLLM proxy API key."
        )
    base = (settings.litellm_api_base or "").strip().rstrip("/")
    if not base:
        raise RuntimeError(
            "Set LITELLM_API_BASE or LITELLM_PROXY_BASE or LITELLM_URL to your LiteLLM proxy "
            "OpenAI-compatible base URL (e.g. http://127.0.0.1:4000/v1)."
        )
    if "/v1" not in base:
        logger.warning(
            "[LiteLLM] base_url %r does not contain /v1; OpenAI-compatible clients expect "
            "e.g. http://127.0.0.1:4000/v1",
            base,
        )
    model_name = settings.chat_model.strip()
    timeout = _request_timeout()

    logger.info("[LiteLLM] ChatOpenAI model=%s base_url=%s", model_name, base)

    # No custom httpx: some LangChain builds reject ``http_async_client`` and 500 every request.
    common = dict(
        base_url=base,
        api_key=settings.litellm_key,
        model=model_name,
        temperature=_temperature(),
    )
    try:
        return ChatOpenAI(**common, timeout=timeout)
    except TypeError:
        return ChatOpenAI(**common, request_timeout=timeout)
