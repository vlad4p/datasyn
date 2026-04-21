# Ingest CSV into DuckDB (pandas optional, then duckdb-mcp)

Load **comma-separated** data into the **Datacyber DuckDB** warehouse using **`duckdb_*`** tools. You may **read the file with pandas first** (same patterns as **`notebooks/read_txt_with_pandas.ipynb`**), then ingest; or load **directly in DuckDB** when the file is simple and trusted.

**Related**

- **Semicolon-separated text, Excel `.xls` / `.xlsx`:** use **`./skills/ingest-pandas-normalize/SKILL.md`** first, produce a **comma CSV**, then apply **this** skill on that file.
- **Notebook reference:** **`./notebooks/read_txt_with_pandas.ipynb`** — `Path`, `pd.read_csv`, `head` / `info`, optional `nrows`, optional `to_csv` to `tmp/`.

---

## Do not use (not in this project)

- **`database_ingest_csv`** (or any `database_*` ingest helper) — not available when only **`duckdb`** is in **`mcp.json`**.
- Do not invent **`ingest_csv`** as a separate MCP tool — use **`duckdb_warehouse_query`** only.

---

## Tools

| MCP tool | Agent-prefixed name | Purpose |
|----------|---------------------|---------|
| `warehouse_list_tables` | **`duckdb_warehouse_list_tables`** | Inspect schemas/tables before create/replace. |
| `warehouse_query` | **`duckdb_warehouse_query`** | DuckDB SQL: `CREATE SCHEMA`, `CREATE TABLE ... AS`, `read_csv_auto`, `COPY`, validation `SELECT`. |

---

## Prerequisites

1. **Source directory is `/data-local/`.** Files available to ingest live under the Docker mount **`/data-local/`** (the repo's `./data-local/`). There is **no** `/inbox`, `/uploads`, `/staging`, `/data`, or any other path. If the user names a file without a directory, assume **`/data-local/<name>`** (possibly nested under a subfolder).
2. **Locate first, then ingest.** Before running any `read_csv*` SQL, confirm the absolute path with **`duckdb_data_local_ls("/data-local", recursive=True, max_depth=3)`** (or a DuckDB `glob('/data-local/**/*<name>*')`). Use the **exact path returned**. Never declare a file missing without that search; if it is truly absent, quote the listing as evidence.
3. **Paths** readable by **DuckDB** inside **`duckdb-mcp`** (that is always the `/data-local/...` mount). Pandas, if used, must use the **same** absolute path.
4. **Encoding** — default **`utf-8`**; match **`read_csv`** and DuckDB options.
5. **Identifiers** — schema/table names: **letters, digits, underscores** only (e.g. **`raw.my_dataset`** with valid segments).

---

## Workflow A — Pandas first, then DuckDB (recommended for exploration / dtype control)

Use this when you want to **inspect** columns, handle **`DtypeWarning`**, or **normalize** to a clean comma CSV before loading.

### A.1 Read with pandas (like the notebook)

Mirror **`notebooks/read_txt_with_pandas.ipynb`** (comma-separated file — default **`sep` is comma**):

```python
from pathlib import Path

import pandas as pd

DATA_PATH = Path("/path/to/data.csv")  # or .txt that is comma-separated

df = pd.read_csv(DATA_PATH, encoding="utf-8")
# If you see DtypeWarning on large files, use:
# df = pd.read_csv(DATA_PATH, encoding="utf-8", low_memory=False)

df.head()
df.info()
```

Optional **probe** without full load:

```python
df_probe = pd.read_csv(DATA_PATH, encoding="utf-8", nrows=5000)
df_probe.shape
```

### A.2 Optional: write a normalized CSV for DuckDB

If you need a **stable path** under **`tmp/`** or next to the source:

```python
OUT_DIR = Path("/path/to/project/tmp")
OUT_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED = OUT_DIR / f"{DATA_PATH.stem}.normalized.csv"
df.to_csv(NORMALIZED, index=False)
```

Use **`str(NORMALIZED.resolve())`** (or the absolute path string) in DuckDB SQL below. If you skip this step, use the **original `DATA_PATH`** string in **`read_csv_auto`**.

### A.3 Ingest into DuckDB

0. **Resolve the file under `/data-local/`** with `duckdb_data_local_ls` (recursive) if you haven't already. Use the exact path returned (for example `/data-local/usu_individual_T325.txt`).
1. **`duckdb_warehouse_list_tables`**
2. **`duckdb_warehouse_query`:**

```sql
CREATE SCHEMA IF NOT EXISTS raw;
```

```sql
CREATE TABLE raw.my_dataset AS
SELECT * FROM read_csv_auto('/data-local/<subdir-if-any>/<file>.csv');
-- example (semicolon TXT): read_csv_auto('/data-local/usu_individual_T325.txt', delim=';', header=true, sample_size=-1)
```

3. Validate with **`COUNT(*)`**, **`LIMIT`**, **`PRAGMA table_info`**.

---

## Workflow B — DuckDB only (no pandas)

When the CSV is already clean and you do not need a pandas preview:

0. **Resolve the file under `/data-local/`** via `duckdb_data_local_ls` (recursive) and use the exact absolute path returned.
1. **`duckdb_warehouse_list_tables`**
2. **`duckdb_warehouse_query`:**

```sql
CREATE SCHEMA IF NOT EXISTS raw;
```

```sql
CREATE TABLE raw.my_dataset AS
SELECT * FROM read_csv_auto('/data-local/<file>.csv');
-- semicolon example: read_csv_auto('/data-local/<file>.txt', delim=';', header=true, sample_size=-1)
```

Or explicit **`COPY`** with **`DELIMITER ','`**, **`HEADER true`**, etc.

---

## Validate

```sql
SELECT COUNT(*) AS row_count FROM raw.my_dataset;
```

```sql
SELECT * FROM raw.my_dataset LIMIT 20;
```

```sql
PRAGMA table_info('raw.my_dataset');
```

---

## Large files and performance

- Prefer **`nrows`** in pandas for exploration; use **`low_memory=False`** when eliminating **`DtypeWarning`** on full read.
- In DuckDB, avoid returning huge result sets through the tool; use **`LIMIT`** and **`COUNT(*)`**.

---

## Failure handling

- **Paths** — Must exist for **duckdb-mcp**’s process (container mount).
- **Types** — Tighten with explicit **`COPY`** column list, or cast in **`CREATE TABLE AS SELECT`**.
- **Replace vs append** — **`DROP TABLE IF EXISTS`** before recreate when replacing.

---

## What to report back

1. Whether you used **Workflow A (pandas)** or **B (DuckDB-only)** and path(s).
2. Pandas: row/column counts or **`info`** summary if used.
3. DuckDB: schema/table, **`COUNT(*)`**, and **`LIMIT`** sample.

---

**Summary:** Optionally **`pandas.read_csv`** (see **`notebooks/read_txt_with_pandas.ipynb`**) → optional **`to_csv`** → **`duckdb_warehouse_list_tables`** + **`duckdb_warehouse_query`** with **`read_csv_auto`** / **`COPY`** and validation SQL.
