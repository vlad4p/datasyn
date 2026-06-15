"""Tests for LiteLLM model catalog helpers."""

from __future__ import annotations

from agent.utils.litellm_models import (
    canonical_litellm_model_id,
    clear_litellm_models_cache,
    filter_litellm_models,
    normalize_litellm_model,
    selectable_litellm_model_ids,
)


def test_normalize_litellm_model() -> None:
    out = normalize_litellm_model({"id": "local/gemini-2.0-flash", "owned_by": "openai"})
    assert out["id"] == "local/gemini-2.0-flash"
    assert out["name"] == "local/gemini-2.0-flash"
    assert "owned_by=openai" in out["description"]


def test_filter_litellm_models_sorts_by_id() -> None:
    raw = [{"id": "z/model"}, {"id": "a/model"}]
    out = filter_litellm_models(raw)
    assert [m["id"] for m in out] == ["a/model", "z/model"]


def test_filter_litellm_models_drops_wildcards_and_bare_aliases() -> None:
    raw = [
        {"id": "deepseek/*"},
        {"id": "deepseek-reasoner"},
        {"id": "deepseek/deepseek-reasoner"},
        {"id": "deepseek-chat"},
        {"id": "deepseek/deepseek-chat"},
        {"id": "gpt-3.5-turbo"},
    ]
    out = filter_litellm_models(raw)
    assert [m["id"] for m in out] == [
        "deepseek/deepseek-chat",
        "deepseek/deepseek-reasoner",
        "gpt-3.5-turbo",
    ]


def test_canonical_litellm_model_id_prefers_namespaced_alias() -> None:
    catalog = {
        "deepseek-reasoner",
        "deepseek/deepseek-reasoner",
        "gpt-3.5-turbo",
    }
    assert canonical_litellm_model_id("deepseek-reasoner", catalog_ids=catalog) == (
        "deepseek/deepseek-reasoner"
    )
    assert canonical_litellm_model_id("gpt-3.5-turbo", catalog_ids=catalog) == "gpt-3.5-turbo"


def test_canonical_litellm_model_id_deepseek_heuristic_without_catalog() -> None:
    assert canonical_litellm_model_id("deepseek-reasoner", catalog_ids=set()) == (
        "deepseek/deepseek-reasoner"
    )


def test_selectable_litellm_model_ids() -> None:
    ids = {
        "deepseek/*",
        "deepseek-reasoner",
        "deepseek/deepseek-reasoner",
        "gpt-3.5-turbo",
    }
    assert selectable_litellm_model_ids(ids) == {
        "deepseek/deepseek-reasoner",
        "gpt-3.5-turbo",
    }


def test_clear_litellm_models_cache() -> None:
    import agent.utils.litellm_models as mod

    mod._cache_models = [{"id": "x"}]  # noqa: SLF001
    mod._cache_key = "test-key"  # noqa: SLF001
    mod._cache_at = 999.0  # noqa: SLF001
    clear_litellm_models_cache()
    assert mod._cache_models is None  # noqa: SLF001
    assert mod._cache_key is None  # noqa: SLF001
