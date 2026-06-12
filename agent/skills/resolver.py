"""Resolve active skills directory for Deep Agents runtime."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.config import settings
from agent.skills.config import SkillsSettings, skills_settings
from agent.skills.sync import pull_skills_from_litellm

logger = logging.getLogger(__name__)

SKILLS_VIRTUAL_DIR = "/skills/"


def skills_virtual_dir() -> str:
    """Virtual path passed to Deep Agents ``skills=[...]``."""
    return SKILLS_VIRTUAL_DIR


def resolve_skills_root(*, cfg: SkillsSettings | None = None) -> Path:
    """Return the on-disk skills root for the configured source."""
    cfg = cfg or skills_settings
    if cfg.source == "local":
        return cfg.local_dir
    return cfg.cache_dir


def ensure_skills_ready(*, cfg: SkillsSettings | None = None) -> Path:
    """Pull from LiteLLM when configured; return the active skills root."""
    cfg = cfg or skills_settings
    if cfg.source == "local":
        root = cfg.local_dir
        if not root.is_dir():
            logger.warning("skills: local dir %s does not exist", root)
        return root

    logger.info(
        "skills: SKILLS_SOURCE=litellm — pulling bundle (plugin=%s, cache=%s)",
        cfg.plugin_name,
        cfg.cache_dir,
    )
    pull_skills_from_litellm(cfg=cfg)
    return cfg.cache_dir


def skills_runtime_snapshot(*, cfg: SkillsSettings | None = None) -> dict[str, str]:
    """Metadata for health/pipeline endpoints."""
    cfg = cfg or skills_settings
    root = resolve_skills_root(cfg=cfg)
    return {
        "source": cfg.source,
        "root": str(root),
        "virtual_path": SKILLS_VIRTUAL_DIR,
        "local_dir": str(cfg.local_dir),
        "cache_dir": str(cfg.cache_dir),
        "plugin_name": cfg.plugin_name,
        "project_root": str(settings.project_root),
    }
