"""Load ``.txt`` prompt files from ``agent/prompts/``."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agent.config import settings
from agent.skills import discover_skills, resolve_skills_root
from agent.deep_agent_constants import DATA_ANALYST_SUBAGENT_TYPE, QUERY_SUBAGENT_TYPE, SANDBOX_PREFIX

logger = logging.getLogger(__name__)


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "prompts"


def _read_agents_md(path: Path) -> str:
    """Read ``AGENTS.md`` tolerantly so a stray non-UTF-8 byte cannot crash brain startup."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    em = "\u2014".encode("utf-8")
    patched = raw.replace(b"\x9d", em).replace(b"\x97", em).replace(b"\x85", "\u2026".encode("utf-8"))
    try:
        return patched.decode("utf-8")
    except UnicodeDecodeError as exc:
        logger.warning(
            "AGENTS.md contains non-UTF-8 bytes (first error at byte %s); decoding as CP1252. "
            "Re-save the file as UTF-8 to silence this warning.",
            exc.start,
        )
        return patched.decode("cp1252", errors="replace")


def load_prompt(filename: str) -> str:
    """Read a UTF-8 prompt file from ``agent/prompts/{filename}``."""
    path = _prompts_dir() / filename
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _response_language_suffix(locale: str) -> str:
    """Append instruction so the model matches the UI language (must be last, high salience)."""
    loc = (locale or "en").strip().lower()
    if loc in ("es", "spanish", "es-ar", "es-es", "es-mx"):
        return (
            "\n\n## Idioma de respuesta (obligatorio)\n\n"
            "Responde **siempre** en **español** (títulos, explicaciones, tablas, listas, errores, "
            "y comentarios en fragmentos de código). Mantén identificadores técnicos, nombres de "
            "herramientas, rutas, SQL y términos de dominio en la forma en que aparezcan en el proyecto "
            "cuando sea lo habitual."
        )
    return (
        "\n\n## Response language (required)\n\n"
        "Reply **always** in **English** (titles, explanations, tables, lists, error messages, and "
        "code comments), unless the user explicitly asks for a different language for a specific quote. "
        "Keep technical identifiers, tool names, paths, and SQL in their conventional form."
    )


def _runtime_skills_inventory() -> list[str]:
    """Return discovered skill names from the active skills root."""
    return discover_skills(resolve_skills_root())


def _warehouse_playbook(*, compact: bool = True) -> str:
    """Warehouse playbook for subagents.

    Default **compact** prompt (~3k chars) keeps subagent context small; set
    ``DATASYN_SUBAGENT_FULL_AGENTS_MD=1`` to inject full ``AGENTS.md``.
    """
    use_full = os.environ.get("DATASYN_SUBAGENT_FULL_AGENTS_MD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not compact or use_full:
        agents = settings.project_root / "AGENTS.md"
        if agents.is_file():
            return _read_agents_md(agents).strip()
        return load_prompt("supervisor_system_prompt.txt")
    return load_prompt("warehouse_subagent_playbook.txt")


def _orchestrator_runtime_appendix(mcp_tool_names: list[str] | None) -> str:
    """Compact runtime appendix for the orchestrator (names only — no full warehouse playbook)."""
    parts: list[str] = []
    deepagents_helpers = [
        "write_todos",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "task",
    ]
    if mcp_tool_names:
        listed = "\n".join(f"- `{n}`" for n in sorted(mcp_tool_names))
        parts.append(
            "\n\n## Runtime MCP tools (subagents only — authoritative names)\n\n"
            "These MCP tools exist in this process but are **not** callable in this orchestrator thread. "
            "When the user asks what tools exist, list these names plus Deep Agents helpers below.\n\n"
            f"{listed}"
        )
    parts.append(
        "\n\n## Runtime Deep Agents tools (orchestrator)\n\n"
        + "\n".join(f"- `{n}`" for n in deepagents_helpers)
        + "\n\n### `task`: `subagent_type` (mandatory)\n\n"
        f"- **`{QUERY_SUBAGENT_TYPE}`** — default for every substantive user turn (full MCP).\n"
        f"- **`{DATA_ANALYST_SUBAGENT_TYPE}`** — DuckDB + Dagster only.\n"
        "- **`general-purpose`** — disabled; do not use.\n\n"
        "Put user goal, response language, and required output (tables, SQL, counts) in **`description`**."
    )
    skills = _runtime_skills_inventory()
    if skills:
        parts.append(
            "\n\n## Runtime skills (names only)\n\n"
            + "\n".join(f"- `{n}`" for n in skills)
        )
    parts.append(f"\n\nWrite Markdown reports under: `{settings.reports_dir}`.")
    return "".join(parts)


def _subagent_runtime_appendix(mcp_tool_names: list[str] | None) -> str:
    """Full MCP tool list for subagents that execute warehouse work."""
    if not mcp_tool_names:
        return ""
    listed = "\n".join(f"- `{n}`" for n in sorted(mcp_tool_names))
    return (
        "\n\n## Runtime MCP tools (authoritative)\n\n"
        "These are the **only** MCP tools in this process. Do not invent other names.\n\n"
        f"{listed}\n\n"
        f"Scratch under `{SANDBOX_PREFIX}`; user reports under `{settings.reports_dir}`."
    )


def orchestrator_system_prompt(
    mcp_tool_names: list[str] | None = None,
    *,
    response_locale: str = "en",
) -> str:
    """Slim orchestrator prompt — delegation + synthesis only (no full ``AGENTS.md``)."""
    parts = [
        load_prompt("orchestrator_system.txt"),
        "\n\n",
        load_prompt("supervisor_orchestrator.txt"),
        _orchestrator_runtime_appendix(mcp_tool_names),
        _response_language_suffix(response_locale),
    ]
    return "".join(parts)


def warehouse_subagent_system_prompt(
    role_prompt_file: str,
    *,
    mcp_tool_names: list[str] | None = None,
    response_locale: str = "en",
    extra_playbooks: list[str] | None = None,
) -> str:
    """Warehouse playbook + role prompt for ``query`` / ``data-analyst`` subagents."""
    parts = [
        _warehouse_playbook(compact=True),
        "\n\n",
        load_prompt(role_prompt_file),
    ]
    for playbook_file in extra_playbooks or []:
        parts.extend(["\n\n", load_prompt(playbook_file)])
    parts.extend(
        [
            _subagent_runtime_appendix(mcp_tool_names),
            _response_language_suffix(response_locale),
        ]
    )
    return "".join(parts)


def supervisor_system_prompt(
    mcp_tool_names: list[str] | None = None,
    *,
    response_locale: str = "en",
) -> str:
    """Alias for ``orchestrator_system_prompt`` (slim main-thread prompt)."""
    return orchestrator_system_prompt(
        mcp_tool_names=mcp_tool_names,
        response_locale=response_locale,
    )
