---
name: create-table
description: >-
  Create DuckDB tables with proper schema, constraints, and documentation.
  Use when the user asks to create a table, define schema, model data,
  or set up a new dataset structure in datasyn-local.
---

# Create DuckDB Table

## SQL execution — always prefer MCP (duckdb_mcp)

The `duckdb_mcp` extension (loaded by `scripts/python/db.py mcp-serve`) exposes
tools like `query`, `describe`, `list_tables`, and `database_info` to the AI agent.

**Always prefer MCP** for SQL queries. The agent calls MCP tools directly — no
terminal commands, no shell invocations.

### MCP tools available

| Tool | Purpose |
|------|---------|
| `query` | Run SELECT queries (read-only) |
| `describe` | Show table schema |
| `list_tables` | List all tables/views |
| `database_info` | Show database summary |
| `export` | Export query results (json/csv/markdown) |

### Fallback: `db.py run-sql`

When MCP cannot handle the task (DDL like `CREATE TABLE`, multi-step procedural
logic, pandas integration), use the direct DB connection:

```bash
uv run python scripts/python/db.py run-sql "SQL..."
```

This connects directly to `data/duckdb/datasyn.duckdb` — not through MCP.
Kill any MCP lock first:

```bash
kill $(lsof -t data/duckdb/datasyn.duckdb 2>/dev/null) 2>/dev/null
```

## Conventions

- Table names: `snake_case`, plural nouns (`articles`, `sales_events`)
- Primary keys: `id` (INTEGER or UUID) or natural key documented in comment
- Timestamps: `created_at TIMESTAMP DEFAULT current_timestamp`
- Never hardcode DB paths — use `db.get_db_path()`, `db.get_landing_path()`

## Workflow

1. **Define purpose** — what entity/event does this table represent?
2. **Draft schema** — columns, types, nullable rules
3. **Create** with SQL (via `db.py run-sql` — DDL is not read-only)
4. **Validate** — `DESCRIBE`, `SELECT COUNT(*)` (via MCP `describe` and `query`)
5. **Document** — add SQL comment or note in report

## Templates

### From scratch — via `db.py run-sql`

```bash
kill $(lsof -t data/duckdb/datasyn.duckdb) 2>/dev/null
uv run python scripts/python/db.py run-sql "
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    source VARCHAR NOT NULL,
    headline VARCHAR,
    body TEXT,
    published_at TIMESTAMP,
    url VARCHAR,
    ingested_at TIMESTAMP DEFAULT current_timestamp
);
"
```

### From query (CREATE TABLE AS SELECT) — via `db.py run-sql`

```bash
kill $(lsof -t data/duckdb/datasyn.duckdb) 2>/dev/null
uv run python scripts/python/db.py run-sql "
CREATE TABLE cleaned_sales AS
SELECT
    order_id,
    CAST(amount AS DECIMAL(12,2)) AS amount,
    CAST(order_date AS DATE) AS order_date
FROM raw_sales
WHERE amount IS NOT NULL;
"
```

### From pandas (fallback — requires direct DB connection)

Only when working with DataFrames. Uses `db.connect()` — **not MCP**:

```python
import pandas as pd
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts/python").resolve()))
import db

con = db.connect()

df = pd.DataFrame({...})
con.register("tmp_df", df)
con.sql("CREATE TABLE my_table AS SELECT * FROM tmp_df")
con.close()
```

## Post-create checklist

Validate via **MCP tools** (preferred):

```
MCP → describe → my_table
MCP → query   → SELECT COUNT(*) FROM my_table
```

Or via terminal (fallback):

```bash
uv run python scripts/python/db.py run-sql "DESCRIBE table_name;"
uv run python scripts/python/db.py run-sql "SELECT COUNT(*) FROM table_name;"
```

## Type reference (DuckDB)

| Use case | Type |
|----------|------|
| IDs | `INTEGER`, `BIGINT`, `UUID` |
| Money | `DECIMAL(12,2)` |
| Text | `VARCHAR`, `TEXT` |
| Dates | `DATE`, `TIMESTAMP` |
| JSON payload | `JSON` |
| Lists | `VARCHAR[]`, `INTEGER[]` |
