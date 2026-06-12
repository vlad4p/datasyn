"""Discover skill folders that contain ``SKILL.md``."""

from __future__ import annotations

from pathlib import Path


def discover_skills(skills_root: Path) -> list[str]:
    """Return sorted skill directory names under ``skills_root/*/SKILL.md``."""
    if not skills_root.is_dir():
        return []
    names: list[str] = []
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        name = skill_md.parent.name.strip()
        if name:
            names.append(name)
    return names


def skills_inventory(skills_root: Path) -> list[dict[str, str]]:
    """UI/API inventory rows for discovered skills."""
    out: list[dict[str, str]] = []
    for name in discover_skills(skills_root):
        out.append({"name": name, "path": f"skills/{name}/SKILL.md"})
    return out
