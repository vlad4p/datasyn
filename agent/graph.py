"""Deep Agents graph factory (leader): model, prompts, filesystem backend, and remote tools."""

from __future__ import annotations

import logging
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.tools import BaseTool

from agent.utils.load_prompt import supervisor_system_prompt
from agent.utils.litellm_chat import build_chat_model
from agent.config import settings

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return settings.project_root


def build_agent(tools: list[BaseTool], *, response_locale: str = "en"):
    """Build the compiled Deep Agent with supervisor prompt and extra tools."""
    root = _project_root()
    tool_names = [getattr(t, "name", repr(t)) for t in tools]
    logger.info(
        "build_agent: tools=%s names=%s skills_path=/skills/ project_root=%s",
        len(tools),
        tool_names,
        root,
    )
    backend = FilesystemBackend(root_dir=str(root), virtual_mode=True)
    model = build_chat_model()
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=supervisor_system_prompt(mcp_tool_names=tool_names, response_locale=response_locale),
        backend=backend,
        name="datacyber-brain",
        skills=["/skills/"],
    )
