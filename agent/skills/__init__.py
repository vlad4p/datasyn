"""Skills discovery, LiteLLM registry sync, and runtime resolution for Deep Agents."""

from agent.skills.config import SkillsSettings, skills_settings
from agent.skills.discovery import discover_skills, skills_inventory
from agent.skills.resolver import ensure_skills_ready, resolve_skills_root, skills_virtual_dir

__all__ = [
    "SkillsSettings",
    "discover_skills",
    "ensure_skills_ready",
    "resolve_skills_root",
    "skills_inventory",
    "skills_settings",
    "skills_virtual_dir",
]
