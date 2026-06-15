"""Unified LLM model catalog for the UI (OpenRouter or LiteLLM proxy)."""

from __future__ import annotations

from typing import Any

from agent.config import settings
from agent.utils.litellm_models import list_litellm_models
from agent.utils.openrouter_models import list_openrouter_models


async def list_llm_models(*, free_only: bool = False, force_refresh: bool = False) -> dict[str, Any]:
    if settings.model_provider == "openrouter":
        return await list_openrouter_models(free_only=free_only, force_refresh=force_refresh)
    if settings.model_provider == "litellm":
        return await list_litellm_models(free_only=free_only, force_refresh=force_refresh)
    return {
        "status": "unsupported",
        "model_provider": settings.model_provider,
        "models": [],
        "count": 0,
        "error": f"Model catalog is not available for MODEL_PROVIDER={settings.model_provider!r}.",
    }
