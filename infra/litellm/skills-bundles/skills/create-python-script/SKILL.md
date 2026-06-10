---
name: create-python-script
description: >-
  Add optional Python helpers under scripts/python/ (not for ingest or
  reports — those are skills). Use when reusable code beyond DuckDB SQL is needed.
---

# Create Python in scripts/python/

## Scope

- **Allowed:** extend `scripts/python/db.py` or new modules in `scripts/python/`
- **Not for:** ingest or report pipelines — use skills `ingest-data` and `statistical-report`
- **SQL queries:** prefer MCP (`db.py run-sql`) over direct `db.connect()` + `con.execute()`

## Workflow

1. Confirm a skill (SQL) is insufficient
2. Add module under `scripts/python/`
3. Reuse `import db` for connections and paths
4. `uv add <package>` if needed
5. Document usage in `scripts/python/README.md`

## SQL execution

When the script needs to run SQL, **prefer MCP** (subprocess call to `db.py run-sql`):

```python
import subprocess
sql = "SELECT COUNT(*) FROM my_table;"
subprocess.run(["uv", "run", "python", "scripts/python/db.py", "run-sql", sql])
```

Only use direct `db.connect()` when MCP cannot handle the task (e.g., pandas/DataFrame operations, multi-step procedural logic).

## Import pattern (for direct DB connection — fallback only)

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts/python").resolve()))
import db

con = db.connect()
```

## Standards

- Run via `uv run python scripts/python/...`
- No secrets in code
