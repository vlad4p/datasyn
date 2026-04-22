"""Load ``.txt`` prompt files from ``src/agent/prompts/``."""

from __future__ import annotations

from pathlib import Path

from agent.config import settings


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "prompts"


def _read_agents_md(path: Path) -> str:
    """Read ``AGENTS.md`` as UTF-8 after normalizing stray Windows-1252 dash/quote bytes."""
    raw = path.read_bytes()
    # Lone 0x9d / 0x97 are invalid in UTF-8 but often appear when em dashes were saved as CP1252.
    em = "\u2014".encode("utf-8")
    raw = raw.replace(b"\x9d", em).replace(b"\x97", em)
    return raw.decode("utf-8")


def load_prompt(filename: str) -> str:
    """Read a UTF-8 prompt file from ``src/agent/prompts/{filename}``."""
    path = _prompts_dir() / filename
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def supervisor_system_prompt(mcp_tool_names: list[str] | None = None) -> str:
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
    if mcp_tool_names:
        listed = "\n".join(f"- `{n}`" for n in sorted(mcp_tool_names))
        parts.append(
            "\n\n## Runtime MCP tools (authoritative)\n\n"
            "These are the **only** MCP tools loaded from `mcp.json` in this process. "
            "If a tool is not in this list, it **does not exist**. When the user asks "
            '"what tools do you have?", answer with **this exact list** (plus the built-in '
            "Deep Agents helpers: `write_todos`, `ls`, `read_file`, `write_file`, `edit_file`, "
            "`glob`, `grep`, `task`). Do **not** mention `database_*`, `process_*`, "
            "`ingest_csv`, `database_ingest_csv`, or any other name not listed below.\n\n"
            f"{listed}"
        )
    parts.append(f"\n\nWrite Markdown reports under: `{settings.reports_dir}`.")
    return "".join(parts)
