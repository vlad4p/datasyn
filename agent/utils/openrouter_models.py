"""Fetch and normalize OpenRouter model catalog for the UI model switch."""

from __future__ import annotations

import time
from typing import Any

import httpx

from agent.config import OPENROUTER_DEFAULT_API_BASE, settings
from agent.utils.litellm_chat import _openrouter_optional_headers

_CACHE_TTL_S = 300.0
_cache_at: float = 0.0
_cache_models: list[dict[str, Any]] | None = None


def is_free_openrouter_model(model: dict[str, Any]) -> bool:
    """True when OpenRouter marks the model as free (``:free`` suffix or zero pricing)."""
    mid = str(model.get("id") or "").strip()
    if mid.endswith(":free"):
        return True
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        return False
    prompt = str(pricing.get("prompt") or "0").strip()
    completion = str(pricing.get("completion") or "0").strip()
    return prompt in ("0", "0.0") and completion in ("0", "0.0")


def normalize_openrouter_model(raw: dict[str, Any]) -> dict[str, Any]:
    """Compact shape for API responses and UI lists."""
    mid = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or mid).strip() or mid
    desc = str(raw.get("description") or "").strip()
    ctx = raw.get("context_length")
    try:
        context_length = int(ctx) if ctx is not None else None
    except (TypeError, ValueError):
        context_length = None
    return {
        "id": mid,
        "name": name,
        "description": desc[:400] if desc else "",
        "context_length": context_length,
        "is_free": is_free_openrouter_model(raw),
    }


def filter_openrouter_models(
    models: list[dict[str, Any]], *, free_only: bool = False
) -> list[dict[str, Any]]:
    out = [normalize_openrouter_model(m) for m in models if str(m.get("id") or "").strip()]
    if free_only:
        out = [m for m in out if m.get("is_free")]
    out.sort(key=lambda m: (not m.get("is_free"), str(m.get("name") or "").lower()))
    return out


async def fetch_openrouter_models_raw(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """GET OpenRouter ``/v1/models`` (text output only). Cached briefly in-process."""
    global _cache_at, _cache_models
    now = time.monotonic()
    if not force_refresh and _cache_models is not None and (now - _cache_at) < _CACHE_TTL_S:
        return _cache_models

    key = settings.openrouter_api_key
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")

    base = (settings.openrouter_api_base or OPENROUTER_DEFAULT_API_BASE).strip().rstrip("/")
    url = f"{base}/models"
    params = {"output_modalities": "text"}
    headers = {"Authorization": f"Bearer {key}", **_openrouter_optional_headers()}
    t = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=t, trust_env=False) as client:
        r = await client.get(url, headers=headers, params=params)
    if r.status_code >= 400:
        preview = (r.text or "")[:500]
        raise RuntimeError(f"OpenRouter models HTTP {r.status_code}: {preview}")

    payload = r.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("OpenRouter models response missing data[]")

    _cache_models = [m for m in data if isinstance(m, dict)]
    _cache_at = now
    return _cache_models


async def list_openrouter_models(*, free_only: bool = False, force_refresh: bool = False) -> dict[str, Any]:
    """Models for UI picker; raises when provider/key is wrong."""
    if settings.model_provider != "openrouter":
        return {
            "status": "unsupported",
            "model_provider": settings.model_provider,
            "models": [],
            "count": 0,
            "error": "Model catalog is only available when MODEL_PROVIDER=openrouter.",
        }
    try:
        raw = await fetch_openrouter_models_raw(force_refresh=force_refresh)
    except Exception as exc:
        return {
            "status": "error",
            "model_provider": "openrouter",
            "models": [],
            "count": 0,
            "error": str(exc)[:500],
        }
    models = filter_openrouter_models(raw, free_only=free_only)
    return {
        "status": "ok",
        "model_provider": "openrouter",
        "models": models,
        "count": len(models),
        "free_only": free_only,
    }
