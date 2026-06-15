"""Tests for runtime LiteLLM key override."""

from __future__ import annotations

from agent.utils.litellm_key_state import (
    effective_litellm_key,
    litellm_key_source,
    set_runtime_litellm_key,
)


def test_runtime_litellm_key_override() -> None:
    before = effective_litellm_key()
    before_source = litellm_key_source()
    try:
        set_runtime_litellm_key("sk-test-virtual-key-1234")
        assert effective_litellm_key() == "sk-test-virtual-key-1234"
        assert litellm_key_source() == "runtime"
    finally:
        set_runtime_litellm_key(None)
        assert effective_litellm_key() == before
        assert litellm_key_source() == before_source
