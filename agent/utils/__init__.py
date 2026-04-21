"""Shared helpers for the agent package (LLM client, message parsing)."""

from agent.utils.litellm_chat import build_chat_model, probe_litellm_proxy, running_in_docker
from agent.utils.load_prompt import load_prompt, supervisor_system_prompt
from agent.utils.messages import last_assistant_text

__all__ = [
    "build_chat_model",
    "last_assistant_text",
    "load_prompt",
    "probe_litellm_proxy",
    "running_in_docker",
    "supervisor_system_prompt",
]
