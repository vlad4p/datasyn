"""Recommended OpenRouter ``:free`` model ids for Datasyn brain tiers.

When ``MODEL_PROVIDER=openrouter`` and ``CHAT_MODEL`` / ``CHAT_MODEL_FAST`` are unset,
``chat_model_state`` applies these defaults so subagents avoid slow 120B free tiers
for simple SQL loops while the orchestrator keeps a stronger synthesis model.
"""

from __future__ import annotations

# Subagents (query / data-analyst): tool-heavy loops — prefer fast flash-tier free models.
OPENROUTER_FREE_FAST_MODEL = "google/gemini-2.0-flash-exp:free"

# Orchestrator: user-facing synthesis — slightly larger free instruct model.
OPENROUTER_FREE_ORCHESTRATOR_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

# Models that are free but too slow for multi-turn SQL subagent work (trace post-mortems).
SLOW_OPENROUTER_FREE_HINTS: frozenset[str] = frozenset(
    {
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3-ultra-253b-a12b:free",
        "openai/gpt-oss-120b:free",
        "deepseek/deepseek-r1:free",
    }
)


def is_openrouter_free_model_id(model_id: str) -> bool:
    mid = (model_id or "").strip()
    return mid.endswith(":free")


def warn_if_slow_free_model(model_id: str, *, tier: str) -> str | None:
    """Return a log-friendly warning when a known-slow free model is used for the fast tier."""
    mid = (model_id or "").strip()
    if tier != "fast" or mid not in SLOW_OPENROUTER_FREE_HINTS:
        return None
    return (
        f"CHAT_MODEL_FAST={mid!r} is a large free model and will be slow for SQL subagent loops. "
        f"Prefer {OPENROUTER_FREE_FAST_MODEL!r} (or another flash/small :free model)."
    )
