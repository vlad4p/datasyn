"""Tests for OpenRouter free-tier model defaults in chat_model_state."""

from __future__ import annotations

from unittest.mock import patch

from agent.utils.chat_model_state import effective_chat_model, effective_fast_chat_model
from agent.utils.openrouter_free_defaults import (
    OPENROUTER_FREE_FAST_MODEL,
    OPENROUTER_FREE_ORCHESTRATOR_MODEL,
)


def test_openrouter_defaults_when_env_unset() -> None:
    fake_settings = type(
        "S",
        (),
        {
            "model_provider": "openrouter",
            "chat_model": None,
            "chat_model_fast": None,
        },
    )()
    with patch("agent.utils.chat_model_state.settings", fake_settings):
        with patch("agent.utils.chat_model_state._runtime_chat_model", None):
            assert effective_chat_model() == OPENROUTER_FREE_ORCHESTRATOR_MODEL
            assert effective_fast_chat_model() == OPENROUTER_FREE_FAST_MODEL


def test_fast_tier_explicit_env_overrides_default() -> None:
    fake_settings = type(
        "S",
        (),
        {
            "model_provider": "openrouter",
            "chat_model": None,
            "chat_model_fast": "mistralai/mistral-small-24b-instruct-2501:free",
        },
    )()
    with patch("agent.utils.chat_model_state.settings", fake_settings):
        assert effective_fast_chat_model() == "mistralai/mistral-small-24b-instruct-2501:free"
