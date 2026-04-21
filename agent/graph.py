"""Deep Agents graph factory (leader): model, prompts, filesystem backend, and remote tools."""

from __future__ import annotations

from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.tools import BaseTool

from agent.utils.load_prompt import supervisor_system_prompt
from agent.utils.litellm_chat import build_chat_model
from agent.config import settings


def _project_root() -> Path:
    return settings.project_root


def build_agent(tools: list[BaseTool]):
    """Build the compiled Deep Agent with supervisor prompt and extra tools."""
    root = _project_root()
    backend = FilesystemBackend(root_dir=str(root), virtual_mode=True)
    model = build_chat_model()
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=supervisor_system_prompt(),
        backend=backend,
        name="datacyber-brain",
    )
