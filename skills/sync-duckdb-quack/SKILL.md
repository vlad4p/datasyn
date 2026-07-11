---
name: sync-duckdb-quack
description: >-
  Sync tables from an external DuckDB (Quack protocol) into the main DuckHouse
  warehouse via duckdb-mcp. Use when the user asks to sync externals, pull remote
  Quack tables, run quack-sync, or refresh medallion.sync_registry.
---

# Sync DuckDB via Quack

## When to use

- Pull tables from an **external** DuckDB that exposes **Quack** (`quack:host:9494`) into the **main** warehouse (the `duckdb` MCP server in `mcp.json`).
- Inspect or refresh **`medallion.sync_registry`**.
- Headless / cron: `uv run quack-sync`.

## Architecture

Sync SQL runs **on the main `duckdb-mcp` process** (one statement per `duckdb_execute_query` call):

1. `INSTALL quack` / `LOAD quack`
2. `CREATE OR REPLACE SECRET … (TYPE quack, TOKEN …, SCOPE …)`
3. `ATTACH 'quack:…' AS <alias> (TYPE quack, TOKEN …, DISABLE_SSL true, READ_ONLY)`
4. Per table: `CREATE OR REPLACE TABLE <target_schema>.<tbl> AS SELECT * FROM <alias>.<schema>.<tbl>`
5. Record row in `medallion.sync_registry`
6. `DETACH <alias>`

Do **not** open `warehouse.duckdb` from the Brain process. Do **not** chain multiple statements with `;`.

## Configuration

### Manifest (non-secret)

[`config/sync_sources.yaml`](../../config/sync_sources.yaml) — source name, alias, target schema, optional table list.

### Env (secrets — `.env` only)

| Variable | Purpose |
|----------|---------|
| `SYNC_<NAME>_QUACK_URI` | e.g. `quack:10.13.10.200:9494` |
| `SYNC_<NAME>_QUACK_TOKEN` | Quack token for that source |
| `EXTERNAL_QUACK_URI` / `EXTERNAL_QUACK_TOKEN` | Fallback when source `name` is `external` |
| `SYNC_TARGET_SCHEMA` | Default target schema (default `bronze`) |
| `QUACK_URI` / `QUACK_TOKEN` | Main warehouse Quack (Dagster / docs; sync itself uses MCP) |

Example source in YAML:

```yaml
sources:
  - name: external
    alias: ext_wh
    target_schema: bronze
    enabled: true
    tables:
      - source_schema: bronze
        source_table: example_table
        target_table: ext_example_table
```

If `tables` is empty, the sync discovers BASE TABLEs under `source_schemas` (default bronze/silver/gold) on the attached alias.

## How to run

### CLI

```bash
uv run quack-sync
uv run quack-sync --source external
uv run quack-sync --status
```

### Brain API / UI

- `POST /sync/run` — body optional `{ "source": "external" }`
- `GET /sync/status` — registry rows + configured sources
- UI panel **Sync & Lineage** — **Sync now** button + table list

### Agent path (MCP)

Prefer the CLI or `/sync/run` for full sync. For ad-hoc single-table copy via tools:

```sql
-- one call each
INSTALL quack;
LOAD quack;
CREATE OR REPLACE SECRET quack_external (TYPE quack, TOKEN '<token>', SCOPE 'quack:host:9494');
ATTACH 'quack:host:9494' AS ext_wh (TYPE quack, TOKEN '<token>', DISABLE_SSL true, READ_ONLY);
CREATE OR REPLACE TABLE bronze.ext_example AS SELECT * FROM ext_wh.bronze.example_table;
DETACH ext_wh;
```

## Registry

```sql
CREATE SCHEMA IF NOT EXISTS medallion;
CREATE TABLE IF NOT EXISTS medallion.sync_registry (
  id BIGINT,
  source_name VARCHAR,
  source_uri VARCHAR,
  source_fqn VARCHAR,
  target_fqn VARCHAR,
  row_count BIGINT,
  status VARCHAR,
  error_message VARCHAR,
  synced_at TIMESTAMP
);
```

Validate with `SELECT * FROM medallion.sync_registry ORDER BY synced_at DESC LIMIT 20`.

## Safety

- Always **READ_ONLY** attach on the external.
- Full replace per table (`CREATE OR REPLACE TABLE`) — not incremental append.
- Never put tokens in the YAML manifest or commit `.env`.
- One SQL statement per MCP call.
