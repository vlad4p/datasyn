"""Load ``.txt`` prompt files from ``src/agent/prompts/``."""

from __future__ import annotations

from pathlib import Path

from agent.config import settings


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    """Read a UTF-8 prompt file from ``src/agent/prompts/{filename}``."""
    path = _prompts_dir() / filename
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def supervisor_system_prompt() -> str:
    """Use project ``AGENTS.md`` when present; otherwise ``supervisor_system_prompt.txt``."""
    root = settings.project_root
    agents = root / "AGENTS.md"
    if agents.is_file():
        base = agents.read_text(encoding="utf-8").strip()
    else:
        base = load_prompt("supervisor_system_prompt.txt")
    return f"{base}\n\nWrite Markdown reports under: `{settings.reports_dir}`."
