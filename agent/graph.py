"""Deep Agents graph factory (leader): model, prompts, filesystem backend, and remote tools."""

from __future__ import annotations

import logging
from pathlib import Path

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool

from agent.middleware import OrchestratorMcpGuardMiddleware
from agent.skills import ensure_skills_ready, resolve_skills_root, skills_virtual_dir
from agent.utils.load_prompt import orchestrator_system_prompt
from agent.utils.litellm_chat import build_chat_model, build_fast_chat_model
from agent.utils.subagents_spec import (
    build_composite_backend,
    data_analyst_subagent,
    disabled_general_purpose_subagent,
    query_subagent,
)
from agent.config import settings

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return settings.project_root


def build_agent(tools: list[BaseTool], *, response_locale: str = "en"):
    """Build the compiled Deep Agent with supervisor prompt and extra tools."""
    root = _project_root()
    skills_root = ensure_skills_ready()
    skills_path = skills_virtual_dir()
    tool_names = [getattr(t, "name", repr(t)) for t in tools]
    orchestrator_model = build_chat_model(tier="default")
    fast_model = build_fast_chat_model()
    logger.info(
        "build_agent: mcp_tools=%s skills_path=%s skills_root=%s orchestrator_model=%s fast_model=%s",
        len(tools),
        skills_path,
        skills_root,
        getattr(orchestrator_model, "model_name", orchestrator_model),
        getattr(fast_model, "model_name", fast_model),
    )
    backend = build_composite_backend(project_root=root, skills_root=skills_root)
    return create_deep_agent(
        model=orchestrator_model,
        tools=[],
        system_prompt=orchestrator_system_prompt(mcp_tool_names=tool_names, response_locale=response_locale),
        middleware=[OrchestratorMcpGuardMiddleware()],
        backend=backend,
        subagents=[
            disabled_general_purpose_subagent(),
            query_subagent(tools=tools, model=fast_model, response_locale=response_locale),
            data_analyst_subagent(tools=tools, model=fast_model, response_locale=response_locale),
        ],
        name="datasyn-brain",
        skills=[skills_path],
    )
