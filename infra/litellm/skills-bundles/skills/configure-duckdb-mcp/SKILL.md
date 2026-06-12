---
name: configure-duckdb-mcp
description: >-
  Configure duckdb_mcp for AI agents. Use for MCP setup in Cursor, VS Code,
  Kilo Code, or any IDE that supports MCP servers over stdio.
---

# Configure DuckDB MCP

References: [duckdb.org](https://duckdb.org/community_extensions/extensions/duckdb_mcp) · [GitHub README](https://github.com/teaguesterling/duckdb_mcp/blob/main/README.md)

## Setup (this repo)

MCP bootstrap is embedded in **`scripts/python/db.py`**:

```python
# start_mcp_stdio_server()
INSTALL duckdb_mcp FROM community;
LOAD duckdb_mcp;
PRAGMA mcp_server_start('stdio');
```

```bash
./scripts/sh/bootstrap.sh
```

Or individually: `uv run python scripts/python/db.py mcp-config` and `mcp-check`.

---

## Cursor

Bootstrap writes `.cursor/mcp.json` pointing to:

```json
{
  "mcpServers": {
    "datasyn-duckdb": {
      "command": "uv",
      "args": ["run", "python", "${workspaceFolder}/scripts/python/db.py", "mcp-serve"],
      "cwd": "${workspaceFolder}",
      "env": {
        "DATASYN_DB_PATH": "${workspaceFolder}/data/duckdb/datasyn.duckdb"
      }
    }
  }
}
```

Command to generate:
```bash
uv run python scripts/python/db.py mcp-config   # writes .cursor/mcp.json
```

Reload MCP in Cursor. Do **not** commit `.cursor/mcp.json`. Template: `.cursor/mcp.json.example`.

---

## VS Code

VS Code uses `.vscode/mcp.json` with the `"servers"` key (not `"mcpServers"`):

```json
{
  "servers": {
    "datasyn-duckdb": {
      "command": "uv",
      "args": ["run", "python", "${workspaceFolder}/scripts/python/db.py", "mcp-serve"],
      "cwd": "${workspaceFolder}",
      "env": {
        "DATASYN_DB_PATH": "${workspaceFolder}/data/duckdb/datasyn.duckdb"
      }
    }
  }
}
```

Steps:
```bash
uv run python scripts/python/db.py mcp-config       # generates .cursor/mcp.json
cp .cursor/mcp.json .vscode/mcp.json                 # copy → VS Code
```

Then edit `.vscode/mcp.json`: change `"mcpServers"` → `"servers"` (VS Code‑specific key).

**VS Code alternative** — settings.json:
Paste the server object inside `.vscode/settings.json` under:
```json
"github.copilot.chat.agent.mcpServers": { … }
```

Reload VS Code window: `Cmd+Shift+P` → "Developer: Reload Window".

---

## Kilo Code

Kilo Code uses the same MCP format as VS Code (`.vscode/mcp.json` with `"servers"`):

```json
{
  "servers": {
    "datasyn-duckdb": {
      "command": "uv",
      "args": ["run", "python", "${workspaceFolder}/scripts/python/db.py", "mcp-serve"],
      "cwd": "${workspaceFolder}",
      "env": {
        "DATASYN_DB_PATH": "${workspaceFolder}/data/duckdb/datasyn.duckdb"
      }
    }
  }
}
```

Steps:
```bash
uv run python scripts/python/db.py mcp-config       # generates .cursor/mcp.json
cp .cursor/mcp.json .vscode/mcp.json                 # copy → VS Code / Kilo Code
```

Then edit `.vscode/mcp.json`: change `"mcpServers"` → `"servers"`.

Reload Kilo Code to pick up the MCP server.

---

## Built-in MCP tools

`query`, `describe`, `list_tables`, `database_info`, `export`.

## Prompts vs skills

- Prompts: `AGENTS.md`
- This file: MCP wiring only
