"""Tests for OpenRouter model catalog helpers."""

from __future__ import annotations

from agent.utils.chat_model_state import (
    effective_chat_model,
    set_runtime_chat_model,
)
from agent.utils.openrouter_models import (
    filter_openrouter_models,
    is_free_openrouter_model,
    normalize_openrouter_model,
)


def test_is_free_by_suffix() -> None:
    assert is_free_openrouter_model({"id": "meta-llama/llama-3.3-70b-instruct:free"}) is True


def test_is_free_by_zero_pricing() -> None:
    assert is_free_openrouter_model(
        {
            "id": "google/gemini-2.0-flash-exp:free",
            "pricing": {"prompt": "0", "completion": "0"},
        }
    ) is True


def test_is_not_free_when_paid() -> None:
    assert is_free_openrouter_model(
        {
            "id": "openai/gpt-4o",
            "pricing": {"prompt": "0.000005", "completion": "0.000015"},
        }
    ) is False


def test_filter_free_only() -> None:
    raw = [
        {"id": "a:free", "name": "A", "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "b/paid", "name": "B", "pricing": {"prompt": "1", "completion": "1"}},
    ]
    all_models = filter_openrouter_models(raw, free_only=False)
    free_models = filter_openrouter_models(raw, free_only=True)
    assert len(all_models) == 2
    assert len(free_models) == 1
    assert free_models[0]["id"] == "a:free"


def test_normalize_openrouter_model_truncates_description() -> None:
    long_desc = "x" * 500
    out = normalize_openrouter_model(
        {"id": "test/model", "name": "Test", "description": long_desc, "context_length": 8192}
    )
    assert out["id"] == "test/model"
    assert out["name"] == "Test"
    assert len(out["description"]) == 400
    assert out["context_length"] == 8192


def test_runtime_chat_model_override() -> None:
    before = effective_chat_model()
    try:
        set_runtime_chat_model("google/gemini-2.0-flash-001")
        assert effective_chat_model() == "google/gemini-2.0-flash-001"
    finally:
        set_runtime_chat_model(None)
        assert effective_chat_model() == before
