"""Load ``.txt`` prompt files from ``src/agent/prompts/``."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.config import settings
from agent.deep_agent_constants import DATA_ANALYST_SUBAGENT_TYPE, SANDBOX_PREFIX

logger = logging.getLogger(__name__)


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "prompts"


def _read_agents_md(path: Path) -> str:
    """Read ``AGENTS.md`` tolerantly so a stray non-UTF-8 byte cannot crash brain startup.

    Strategy: try strict UTF-8 first; on failure, normalize the few CP1252 mojibake bytes
    we have seen in practice (em dash, ellipsis) and retry; if still invalid, fall back to
    CP1252 decoding (a superset of Latin-1) and log a warning. The prompt only feeds the
    LLM, so a best-effort decode is far safer than aborting ``create_deep_agent``.
    """
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
    """Read a UTF-8 prompt file from ``src/agent/prompts/{filename}``."""
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
    """Return discovered skill names under ``<project_root>/skills/*/SKILL.md``."""
    skills_root = settings.project_root / "skills"
    if not skills_root.is_dir():
        return []
    names: list[str] = []
    for p in sorted(skills_root.glob("*/SKILL.md")):
        parent = p.parent.name.strip()
        if parent:
            names.append(parent)
    return names


def supervisor_system_prompt(
    mcp_tool_names: list[str] | None = None,
    *,
    response_locale: str = "en",
) -> str:
    """Use project ``AGENTS.md`` when present; otherwise ``supervisor_system_prompt.txt``.

    When ``mcp_tool_names`` is provided, the actual runtime MCP tools (from ``mcp.json``) are appended to
    the prompt so the model cannot invent names from other products.
    """
    root = settings.project_root
    agents = root / "AGENTS.md"
    if agents.is_file():
        base = _read_agents_md(agents).strip()
    else:
        base = load_prompt("supervisor_system_prompt.txt")

    parts: list[str] = [base]
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
            "\n\n## Runtime MCP tools (authoritative)\n\n"
            "These are the **only** MCP tools loaded from `mcp.json` in this process. "
            "If a tool is not in this list, it **does not exist**. When the user asks "
            '"what tools do you have?", answer with **this exact list** (plus the built-in '
            "Deep Agents helpers: `write_todos`, `ls`, `read_file`, `write_file`, `edit_file`, "
            "`glob`, `grep`, `task`). Do **not** mention `database_*`, `process_*`, "
            "`ingest_csv`, `database_ingest_csv`, legacy warehouse aliases (`warehouse_query`, "
            "`duckdb_warehouse_query`), or any other name not listed below.\n\n"
            f"{listed}"
        )
        parts.append(
            "\n\n## Runtime Deep Agents tools (authoritative)\n\n"
            "These are runtime-provided helper tools available in this process:\n\n"
            + "\n".join(f"- `{n}`" for n in deepagents_helpers)
            + "\n\n### Filesystem: sandbox (ephemeral)\n\n"
            f"Virtual path **`{SANDBOX_PREFIX}`** is a **session sandbox** (not persisted to disk). "
            "Use it for scratch notes, intermediate extracts, and drafts. "
            f"Final user-facing reports and artifacts go under `{settings.reports_dir}` (or paths you agree with the user). "
            "The main project tree is still available for reading skills, `AGENTS.md`, and existing reports.\n\n"
            "### `task`: `subagent_type` (mandatory — pick one)\n\n"
            "The **`task`** tool delegates work to a short-lived subagent. **`subagent_type`** must be "
            "exactly one of the configured types below—anything else fails.\n\n"
            "- **`general-purpose`** — Full MCP tool set (same servers as this agent): scraping, DuckDB, Dagster, "
            "skills, filesystem. Use for complex multi-step work that benefits from isolation, parallel delegations, "
            "or heavy context.\n\n"
            f"- **`{DATA_ANALYST_SUBAGENT_TYPE}`** — **DuckDB + Dagster MCP tools only** (no `storage_*`). "
            "Use for deep warehouse analytics, multi-step SQL, catalog/metadata lookups via "
            "`dagster_catalog_*`, and Dagster code-location operations—especially when you want to keep "
            "the main thread small or delegate pipeline/database analysis without scraper noise.\n\n"
            "Put detailed instructions in **`description`** (goal, constraints, expected return shape). "
            "For trivial chat or one-off tool calls, answer directly—do **not** spawn a subagent."
        )
    skills = _runtime_skills_inventory()
    if skills:
        parts.append(
            "\n\n## Runtime skills (authoritative)\n\n"
            "These are the skills currently discovered from `/skills/*/SKILL.md`:\n\n"
            + "\n".join(f"- `{n}`" for n in skills)
        )
    else:
        parts.append(
            "\n\n## Runtime skills (authoritative)\n\n"
            "No skills were discovered under `/skills/*/SKILL.md`."
        )
    if mcp_tool_names:
        parts.append(
            "\n\n## Dagster project safety\n\n"
            "For Dagster code-location work, operate with `dagster_*` tools only "
            "(`dagster_list_projects` → `dagster_create_project` → `dagster_add_*`). "
            "Do **not** use Deep Agents filesystem helpers (`write_file`, `edit_file`, etc.) "
            "to modify `/projects/...` because that path belongs to the dagster-mcp container "
            "mount and helper-tool updates there can be misleading.\n\n"
            "Never execute SQL/code with placeholder paths (`path/to/...`, `your_file_here`, etc.). "
            "First resolve a real absolute path from tool output (typically under `/data-local/...`, "
            "which is the DuckDB compatibility mirror of MinIO landing data) "
            "and then reuse that exact path.\n\n"
            "## Delegation hint\n\n"
            f"When the user needs substantial **database analytics**, **catalog SQL**, or **Dagster pipeline work**, "
            f"prefer spawning **`task`** with **`subagent_type=\"{DATA_ANALYST_SUBAGENT_TYPE}\"`** so analysis runs "
            "in an isolated context with only DuckDB and Dagster tools; handle scraping and mixed workflows "
            "yourself or via **`general-purpose`**.\n\n"
            "If they ask for **tablas**, **DISTINCT**, **agrupar por descripción**, or similar: put in **`description`** "
            "the **fully qualified table**, columns, and that the return must include **Markdown pipe tables** "
            "plus **fenced SQL** and counts—not prose-only summaries."
        )
    parts.append(f"\n\nWrite Markdown reports under: `{settings.reports_dir}`.")
    parts.append(_response_language_suffix(response_locale))
    return "".join(parts)
