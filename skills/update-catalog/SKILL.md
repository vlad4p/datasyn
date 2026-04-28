---
name: update-catalog
description: >-
  Registers new DuckDB tables/views in the data catalog or updates metadata for
  an existing dataset. Uses warehouse MCP to introspect schema, **dagster-mcp**
  (`dagster_catalog_execute_query`) to upsert entity_json and refresh tag_usage /
  entity_relationship; asks the user for tags, owners, descriptions, and lineage
  when needed. Use when the user wants to catalog a table, register metadata,
  sync the catalog with the warehouse, or enrich/update dataset documentation.
  For INDEC EPH gold FQNs left sparse by bad traces (empty columns, missing tags),
  run scripts/repair_eph_dataset_entity.py per the Host repair utility section.
---

# Update catalog (register or enrich)

The **brain** (this agent) is the only place that ties **DuckDB** and the **metadata catalog** together. **Never** connect the catalog database to the warehouse: there is no direct catalog→DuckDB link. You **read schema from DuckDB** via **`duckdb_*`** tools and **write metadata** as SQL through **`dagster_catalog_execute_query`**.

## When to use

- A **new** table/view exists in DuckDB but has **no** (or partial) **catalog** entry.
- The user wants to **update** descriptions, **tags**, **owners**, **column** text, or **lineage** for an **existing** FQN.
- The user said "register this table", "add to the catalog", "update catalog metadata", "document this dataset".

## Tool routing (mandatory)

**dagster-mcp** exposes only **`dagster_catalog_get_schema`** and **`dagster_catalog_execute_query`** — there is **no** `catalog_register_or_update_dataset` / `catalog_set_lineage` / `catalog_get_dataset` tool. Every catalog read/write below is a SQL statement built by the brain and run through **`dagster_catalog_execute_query`** (one statement per call). See **`./skills/catalog-sql/SKILL.md`** for the base SQL shapes.

| Step | Server | Tool | Purpose |
|------|--------|------|---------|
| List objects | `duckdb` | **`duckdb_get_schema`** | Find `table_schema`, `table_name`, `table_type`. |
| Column types | `duckdb` | **`duckdb_execute_query`** | `PRAGMA table_info('schema.table')` and/or `information_schema.columns`. |
| Optional counts | `duckdb` | **`duckdb_execute_query`** | `SELECT COUNT(*)`, `NULL` rates — only if useful for the description; keep **`LIMIT`** in mind. |
| Catalog layout | `dagster` | **`dagster_catalog_get_schema`** | Confirm table / column names on first run of a session. |
| Check existing | `dagster` | **`dagster_catalog_execute_query`** | `SELECT id, entity_json FROM dataset_entity WHERE fully_qualified_name = '<fqn>'` (or the FTS query from `catalog-sql`). |
| Upsert entity | `dagster` | **`dagster_catalog_execute_query`** | `INSERT INTO dataset_entity (fully_qualified_name, entity_json) VALUES ('<fqn>', '<json>'::jsonb) ON CONFLICT (fully_qualified_name) DO UPDATE SET entity_json = EXCLUDED.entity_json RETURNING id`. |
| Refresh tags | `dagster` | **`dagster_catalog_execute_query`** | Two statements (two calls): `DELETE FROM tag_usage WHERE target_id = <id>;` then one `INSERT INTO tag_usage …` per tag. |
| Refresh lineage | `dagster` | **`dagster_catalog_execute_query`** | Delete upstream/downstream edges for the dataset id, then `INSERT INTO entity_relationship …` per resolved FQN (never self-edges). |

Do **not** use PostgreSQL, `psql`, or a direct connection string to the **catalog** from here except through **`dagster_catalog_execute_query`** (that is the supported path).

## FQN and naming

Use a **stable** OpenMetadata-style **fullyQualifiedName** aligned with the project, e.g.:

`duckdb-warehouse.<database_segment>.<schema>.<table>`

- **database_segment:** Often **`main`** for a single default DuckDB database; if the project already uses another segment in the UI, **match existing** FQNs (`SELECT fully_qualified_name FROM dataset_entity ORDER BY updated_at DESC LIMIT 50`).
- **`service`** / **`database`** / **`schema`** / **`name`** inside `entity_json` must **match** the FQN story (same schema/table the user asked for).

`name` is typically the **table** name; `displayName` can be a human label.

## `entity_json` minimal shape

Everything the UI reads comes from `entity_json`. Keep these keys consistent so `summarize_entity_json` (used by `GET /catalog/datasets`) produces a useful row:

```json
{
  "fullyQualifiedName": "duckdb-warehouse.main.raw.my_table",
  "name": "my_table",
  "displayName": "My Table",
  "description": "...",
  "tableType": "Regular",
  "service": { "name": "duckdb-warehouse", "type": "DatabaseService" },
  "database": { "name": "main" },
  "schema":   { "name": "raw" },
  "columns":  [ { "name": "col_a", "dataType": "BIGINT", "description": "" } ],
  "tags":     [ { "tagFQN": "Tier.PII", "source": 0 } ],
  "owners":   [ ],
  "glossaryTerms": [ ],
  "upstreamLineage":   [ ],
  "downstreamLineage": [ ],
  "sourceUrl": "",
  "customProperties": { },
  "createdAt": "...",
  "updatedAt": "..."
}
```

## Schema introspection (DuckDB SQL)

Call **`duckdb_execute_query`** with read-only SQL, for example:

```sql
PRAGMA table_info('raw.my_table');
```

Or:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'raw' AND table_name = 'my_table'
ORDER BY ordinal_position;
```

Map result rows into the `columns` array of `entity_json`:

```json
[
  {"name": "col_a", "dataType": "BIGINT",  "description": ""},
  {"name": "col_b", "dataType": "VARCHAR", "description": ""}
]
```

Add per-column descriptions when the user provides them.

## Ask the user (do not guess)

If anything below is **missing** or unclear, **ask** before the upsert (one focused turn or a short checklist):

- **Description** and **display name** for the **dataset** (table/view).
- **Tags** (domain, PII, refresh cadence, source system).
- **Owners** (team or people identifiers — match your org's format).
- **Glossary terms** if used.
- **Lineage:** upstream file path under `/data-local/...` (as `sourceUrl` / `customProperties`) and/or **upstream table FQNs**; downstream consumers if any.

On **update**, if the user only changes tags or description, still do the `SELECT entity_json FROM dataset_entity WHERE fully_qualified_name = '<fqn>'` first, merge your edits into that document, and upsert so **columns** and **lineage** stay consistent unless the user asked to change them.

## Workflow

1. **Resolve target** — Table/view name or FQN. If unknown, **`duckdb_get_schema`**, then match with the FTS query from **`./skills/catalog-sql/SKILL.md`** (`search_tsv @@ plainto_tsquery(...)`).
2. **If already cataloged** — `SELECT id, entity_json FROM dataset_entity WHERE fully_qualified_name = '<fqn>'`. Use it as the base for an **update**; do not drop lineage unless the user requires it.
3. **Introspect** — `PRAGMA table_info(...)` (and optional stats) via **`duckdb_execute_query`**.
4. **Collect** business metadata (tags, owners, descriptions, lineage) from the user when not provided.
5. **Build** the `columns` array from introspection + user text and assemble the full `entity_json`.
6. **Upsert** the row with one `INSERT … ON CONFLICT (fully_qualified_name) DO UPDATE … RETURNING id` call. Capture the returned `id`.
7. **Refresh `tag_usage`** — one `DELETE` call, then one `INSERT` per tag (each is its own `dagster_catalog_execute_query` call; the guard rejects multi-statement SQL).
8. **Refresh lineage** — `DELETE FROM entity_relationship WHERE (from_id = <id> OR to_id = <id>) AND relation IN ('upstream','downstream')`, then per FQN resolve the other `id` and `INSERT INTO entity_relationship (from_id, to_id, from_entity, to_entity, relation) VALUES (…) ON CONFLICT DO NOTHING`. Never insert self-edges.
9. **Confirm** — final `SELECT entity_json FROM dataset_entity WHERE fully_qualified_name = '<fqn>'` and show the document in the reply.

## Host repair utility (INDEC EPH gold)

When **Langfuse / agent traces** (or manual SQL) wrote **`dataset_entity`** rows for the two fixed INDEC EPH tables with **thin `entity_json`** — e.g. **`"columns": []`**, no **`tags`**, no **`customProperties.ingestHistory`**, no OpenData-style **`sourceUrl` / publisher`** — use the repo **host script** to **rebuild** those documents from live DuckDB + quarter **`metadata.json`**. This complements **`dagster_catalog_execute_query`**: the script uses **bound parameters** (no fragile nested quotes) and matches the **mandatory** column + governance shape in **§ Anti-patterns** below.

| Item | Detail |
|------|--------|
| **Script** | **`scripts/repair_eph_dataset_entity.py`** (docstring at top of file). |
| **Targets** | **`duckdb-warehouse.main.gold.indec_eph_usu_hogar`** and **`duckdb-warehouse.main.gold.indec_eph_usu_individual`** only. |
| **What it writes** | Full **`columns`** from **`information_schema.columns`**, **`entity_json.tags`** (INDEC / EPH / labor theme), **`customProperties.ingestHistory`** — **one entry per `(ANO4, TRIMESTRE)` slice** auto-detected from DuckDB, with per-slice **`rowCount`**, logical `dataLocalTxtPath`, optional **`metadata.json`** **`sha256`** / **`pageUrl`** / **`fetchedAtUtc`** — plus **`tag_usage`** refresh. |
| **When to run** | After detecting sparse rows (`SELECT jsonb_array_length(entity_json->'columns') …`), or when the user asks to **repair / resync** catalog metadata for EPH gold without re-driving the whole agent. |
| **When not to use** | Normal **first-time registration** should still go through **Workflow** above (MCP tools only). The script **replaces** **`entity_json`** for those two FQNs on upsert. |

**Slice autodetect.** The script queries `SELECT ANO4, TRIMESTRE, COUNT(*) FROM gold.<table> GROUP BY 1,2` and builds one **`ingestHistory`** entry per result row. `--hogar-txt` / `--individual-txt` / `--metadata-json` are **repeatable** flags that *enrich* slices by matching `year + quarter` (paths are parsed via the `usu_*_T<q><yy>.txt` filename convention). Slices present in DuckDB with no matching path still get an entry (with `rowCount` and `year/quarter`); paths passed for periods not present in DuckDB are silently ignored.

**Run (repo root, host has both files and network to Postgres):**

```bash
uv run --with duckdb --with 'psycopg[binary]' scripts/repair_eph_dataset_entity.py \
  --duckdb /path/to/warehouse.duckdb \
  --database-url postgresql://datacyber:datacyber@127.0.0.1:5433/datacyber_catalog \
  --metadata-json data-local/indec/mercado_laboral/EPH/2025/Q1/metadata.json \
  --metadata-json data-local/indec/mercado_laboral/EPH/2025/Q2/metadata.json \
  --hogar-txt /data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_hogar_T125.txt \
  --hogar-txt /data-local/indec/mercado_laboral/EPH/2025/Q2/usu_hogar_T225.txt \
  --individual-txt /data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_individual_T125.txt \
  --individual-txt /data-local/indec/mercado_laboral/EPH/2025/Q2/usu_individual_T225.txt
```

**Docker volume** (read-only warehouse file, Postgres on host `5433`):

```bash
docker run --rm \
  -v datacyber-mcp_duckdb_data:/duck:ro \
  -v "$(pwd)":/work:ro \
  --add-host=host.docker.internal:host-gateway \
  python:3.12-slim-bookworm bash -lc \
  "pip install -q duckdb 'psycopg[binary]' && cd /work && python scripts/repair_eph_dataset_entity.py \
    --duckdb /duck/warehouse.duckdb \
    --database-url postgresql://datacyber:datacyber@host.docker.internal:5433/datacyber_catalog \
    --metadata-json data-local/indec/mercado_laboral/EPH/2025/Q1/metadata.json \
    --metadata-json data-local/indec/mercado_laboral/EPH/2025/Q2/metadata.json \
    --hogar-txt /data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_hogar_T125.txt \
    --hogar-txt /data-local/indec/mercado_laboral/EPH/2025/Q2/usu_hogar_T225.txt \
    --individual-txt /data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_individual_T125.txt \
    --individual-txt /data-local/indec/mercado_laboral/EPH/2025/Q2/usu_individual_T225.txt"
```

**INDEC ingest pipeline** also references this utility under **`./skills/ingest-indec-mercadolaboral/SKILL.md`** §6 (mandatory catalog sequence).

## Anti-patterns

- **Ingesting** or **`duckdb_list_data_mount`** just to "prepare" a catalog update — **not required** for registration if the table already exists in DuckDB; only use file paths the user or lineage gives you.
- **Inventing** FQNs that duplicate an existing service/database/schema table under another name — search `dataset_entity` first.
- **Omitting** the `SELECT entity_json` read before updates when lineage or column docs must be preserved.
- **Claiming** that `catalog_register_or_update_dataset`, `catalog_set_lineage`, `catalog_list_datasets`, `catalog_search_datasets`, or `catalog_get_dataset` exist — they don't; **dagster-mcp** only exposes `dagster_catalog_get_schema` and `dagster_catalog_execute_query` for the metadata database.
- **Empty `columns` array** (`"columns": []`) when the warehouse table already exists — always run **`PRAGMA table_info('schema.table')`** or **`information_schema.columns`** via **`duckdb_execute_query`** first and populate **`name`**, **`dataType`**, **`description`** for every column (OpenData / data-dictionary expectation).
- **Bare `UPDATE dataset_entity SET entity_json = '…'`** or **`INSERT … VALUES`** **without** **`ON CONFLICT (fully_qualified_name) DO UPDATE`** for the same FQN — use one **idempotent upsert** per dataset; merge prior **`entity_json`** when the row exists so **`ingestHistory`**, lineage, and column docs are not dropped.
- **Single-quoted JSON blobs in traces** (nested `'` vs `"` confusion) — prefer **PostgreSQL dollar-quoting** (`$json$…$json$::jsonb`) or pass JSON as a bound parameter from code; never ship half-escaped JSON inside a one-line SQL string from the model.
- **Skipping `tag_usage`** when **`entity_json.tags`** is non-empty — after upsert **`RETURNING id`**, **`DELETE FROM tag_usage WHERE target_id = <id>`** then **`INSERT INTO tag_usage …`** per tag (see Workflow §7).
- **Omitting OpenData-style provenance** for public microdata — at minimum set **`sourceUrl`**, **`customProperties.publisher`**, **`customProperties.ingestHistory`** (file path under **`/data-local/…`**, optional **`sourceSha256`** from **`metadata.json`**), and domain/product labels when the dataset is government open data.

## Related

- SQL patterns: **`./skills/catalog-sql/SKILL.md`**
- Load data first (when needed): **`./skills/ingest-indec-mercadolaboral/SKILL.md`** for INDEC EPH under **`/data-local/indec/mercado_laboral/`**; for other file patterns use **`duckdb_execute_query`** with **`read_csv_auto`** / **`read_csv`** directly per **`AGENTS.md`** → **Ingest and delimited data**.
- System rules: **`AGENTS.md`**, **Catalog discipline** and **Catalog-first**
