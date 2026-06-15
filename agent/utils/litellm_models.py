"""Fetch and normalize LiteLLM proxy model catalog for the UI model switch."""

from __future__ import annotations

import time
from typing import Any

import httpx

from agent.config import settings
from agent.utils.litellm_key_state import effective_litellm_key

_CACHE_TTL_S = 300.0
_cache_at: float = 0.0
_cache_key: str | None = None
_cache_models: list[dict[str, Any]] | None = None


def clear_litellm_models_cache() -> None:
    """Drop cached ``/v1/models`` (e.g. after virtual key override)."""
    global _cache_at, _cache_key, _cache_models
    _cache_at = 0.0
    _cache_key = None
    _cache_models = None


def _model_ids(models: list[dict[str, Any]]) -> set[str]:
    return {str(m.get("id") or "").strip() for m in models if str(m.get("id") or "").strip()}


def _is_litellm_wildcard_model_id(model_id: str) -> bool:
    return "*" in model_id


def _prefixed_litellm_alias(model_id: str, catalog_ids: set[str]) -> str | None:
    """Return ``provider/<bare>`` when ``catalog_ids`` contains a namespaced duplicate."""
    bare = model_id.strip()
    if not bare or "/" in bare or _is_litellm_wildcard_model_id(bare):
        return None
    matches = [cid for cid in catalog_ids if "/" in cid and cid.rsplit("/", 1)[-1] == bare]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        matches.sort(key=str.lower)
        return matches[0]
    return None


def selectable_litellm_model_ids(catalog_ids: set[str]) -> set[str]:
    """Drop wildcard entries and bare aliases that duplicate a namespaced id."""
    out: set[str] = set()
    for mid in catalog_ids:
        if _is_litellm_wildcard_model_id(mid):
            continue
        if "/" not in mid and _prefixed_litellm_alias(mid, catalog_ids):
            continue
        out.add(mid)
    return out


def cached_litellm_model_ids() -> set[str]:
    """Model ids from the in-process ``/v1/models`` cache (empty when uncached)."""
    if not _cache_models:
        return set()
    return _model_ids(_cache_models)


def canonical_litellm_model_id(
    model_id: str,
    *,
    catalog_ids: set[str] | None = None,
) -> str:
    """Resolve LiteLLM model aliases to ids that pass virtual-key glob rules.

    Fleet proxies often expose both ``deepseek-reasoner`` and ``deepseek/deepseek-reasoner``.
    Keys restricted to ``deepseek/*`` accept only the prefixed id.
    """
    cleaned = (model_id or "").strip()
    if not cleaned or _is_litellm_wildcard_model_id(cleaned):
        return cleaned
    ids = catalog_ids if catalog_ids is not None else cached_litellm_model_ids()
    if "/" in cleaned:
        return cleaned
    prefixed = _prefixed_litellm_alias(cleaned, ids) if ids else None
    if prefixed:
        return prefixed
    # Heuristic when catalog is not loaded yet (common deepseek alias shape).
    if cleaned.startswith("deepseek-"):
        return f"deepseek/{cleaned}"
    return cleaned


def normalize_litellm_model(raw: dict[str, Any]) -> dict[str, Any]:
    """Compact shape for API responses and UI lists (OpenAI-compatible ``/v1/models``)."""
    mid = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or mid).strip() or mid
    owned = raw.get("owned_by")
    desc = f"owned_by={owned}" if owned else ""
    return {
        "id": mid,
        "name": name,
        "description": desc[:400] if desc else "",
        "context_length": None,
        "is_free": False,
    }


def filter_litellm_models(models: list[dict[str, Any]], *, free_only: bool = False) -> list[dict[str, Any]]:
    del free_only  # LiteLLM catalog has no standard free flag; param kept for API parity.
    ids = _model_ids(models)
    allowed = selectable_litellm_model_ids(ids)
    out = [
        normalize_litellm_model(m)
        for m in models
        if str(m.get("id") or "").strip() in allowed
    ]
    out.sort(key=lambda m: str(m.get("id") or "").lower())
    return out


async def fetch_litellm_models_raw(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """GET LiteLLM ``/v1/models`` using the effective virtual key. Cached briefly in-process."""
    global _cache_at, _cache_key, _cache_models
    key = effective_litellm_key()
    if not key:
        raise RuntimeError("LITELLM_KEY is not configured.")

    cache_identity = key[-8:] if len(key) >= 8 else key
    now = time.monotonic()
    if (
        not force_refresh
        and _cache_models is not None
        and _cache_key == cache_identity
        and (now - _cache_at) < _CACHE_TTL_S
    ):
        return _cache_models

    base = (settings.litellm_api_base or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("LITELLM_PROXY_BASE (or LITELLM_API_BASE) is not configured.")

    url = f"{base}/models"
    t = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=t, trust_env=False) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
    if r.status_code >= 400:
        preview = (r.text or "")[:500]
        raise RuntimeError(f"LiteLLM models HTTP {r.status_code}: {preview}")

    payload = r.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("LiteLLM models response missing data[]")

    _cache_models = [m for m in data if isinstance(m, dict)]
    _cache_at = now
    _cache_key = cache_identity
    return _cache_models


async def list_litellm_models(*, free_only: bool = False, force_refresh: bool = False) -> dict[str, Any]:
    """Models for UI picker when ``MODEL_PROVIDER=litellm``."""
    if settings.model_provider != "litellm":
        return {
            "status": "unsupported",
            "model_provider": settings.model_provider,
            "models": [],
            "count": 0,
            "error": "Model catalog is only available when MODEL_PROVIDER=litellm.",
        }
    try:
        raw = await fetch_litellm_models_raw(force_refresh=force_refresh)
    except Exception as exc:
        return {
            "status": "error",
            "model_provider": "litellm",
            "models": [],
            "count": 0,
            "error": str(exc)[:500],
        }
    models = filter_litellm_models(raw, free_only=free_only)
    return {
        "status": "ok",
        "model_provider": "litellm",
        "models": models,
        "count": len(models),
        "free_only": free_only,
    }
