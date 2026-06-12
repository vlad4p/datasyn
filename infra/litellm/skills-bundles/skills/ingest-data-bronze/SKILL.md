---
name: ingest-data-bronze
description: >-
  Ingest raw files from data/landing into the bronze schema. First layer
  of the medallion pattern — preserve originals, no transformations.
  Supports CSV, TSV, JSON, JSONL, Parquet, XLSX. Use when importing,
  scraping, or loading raw data into DuckDB for the first time.
---

# Ingest data — Bronze (raw layer)

**Zone:** Bronze — `bronze.*` schema.
**Source:** files in `data/landing/` or direct scrapes.
**Goal:** load raw data as-is into DuckDB tables. No cleaning, no joins.

---

## Start here — analyze before you act

1. **What is the source?** → landing file (CSV, JSON, Parquet, etc.) or scrape result
2. **Is it raw?** → yes → this is **bronze**
3. **Any transformations needed?** → no → bronze; if yes → consider **silver** after this step

---

## Workflow

1. **Inspect** — format, encoding, headers (`head`, `file`, or MCP `query` with `read_* LIMIT 5`)
2. **Create schema** — `CREATE SCHEMA IF NOT EXISTS bronze`
3. **Choose load strategy** → see format matrix below
4. **Create table** — `CREATE OR REPLACE TABLE bronze.{name} AS SELECT ... FROM read_*`
5. **Validate** — `COUNT(*)`, `DESCRIBE`, sample rows via MCP

---

## Format matrix

| Format | Extension | DuckDB approach | Notes |
|--------|-----------|-----------------|-------|
| CSV | `.csv` | `read_csv_auto('path')` | Add `header=true`, `delim=';'`, `encoding='UTF-8'` as needed |
| TSV | `.tsv`, `.txt` | `read_csv('path', delim='\t', header=true)` | |
| JSON array | `.json` | `read_json_auto('path')` | |
| JSON Lines | `.jsonl`, `.ndjson` | `read_json_auto('path', format='newline_delimited')` | |
| Parquet | `.parquet` | `read_parquet('path')` | |
| XLSX / XLS | `.xlsx`, `.xls` | `read_xlsx('path')` | `INSTALL excel FROM community; LOAD excel;` first |
| Multiple CSV | `*.csv` | `read_csv(['a.csv','b.csv'], union_by_name=true)` | Or ingest separately |
| Existing DuckDB | `.duckdb` | `ATTACH 'path' AS src; CREATE TABLE AS SELECT * FROM src.main.table` | |
| Plain SQL dump | `.sql` | Execute statements in a controlled session | Review before run |

---

## SQL templates

Tables go into `bronze.*`. Use `CREATE OR REPLACE` for idempotent loads.

```sql
-- CSV (default)
CREATE OR REPLACE TABLE bronze.my_table AS
SELECT * FROM read_csv_auto('data/landing/file.csv');

-- TSV
CREATE OR REPLACE TABLE bronze.my_table AS
SELECT * FROM read_csv('data/landing/file.tsv', delim = '\t', header = true);

-- JSON Lines
CREATE OR REPLACE TABLE bronze.my_table AS
SELECT * FROM read_json_auto('data/landing/file.jsonl', format = 'newline_delimited');

-- Parquet
CREATE OR REPLACE TABLE bronze.my_table AS
SELECT * FROM read_parquet('data/landing/file.parquet');

-- XLSX
INSTALL excel FROM community;
LOAD excel;
CREATE OR REPLACE TABLE bronze.my_table AS
SELECT * FROM read_xlsx('data/landing/file.xlsx', sheet = 'Sheet1');
```

### Typed / messy CSV

```sql
CREATE OR REPLACE TABLE bronze.my_table AS
SELECT * FROM read_csv(
  'data/landing/file.csv',
  header = true,
  ignore_errors = true,
  encoding = 'latin-1'
);
```

### Nested JSON

```sql
CREATE OR REPLACE TABLE bronze.my_table AS
SELECT * FROM read_json('data/landing/file.json');
-- follow with UNNEST / struct extraction in further SQL
```

---

## Validation (via MCP)

```sql
SELECT COUNT(*) AS rows FROM bronze.my_table;
DESCRIBE bronze.my_table;
SELECT * FROM bronze.my_table LIMIT 5;
```

---

## Error handling

| Issue | Action |
|-------|--------|
| Wrong delimiter | Set `delim` explicitly |
| Encoding | `encoding='latin-1'` or convert file in landing |
| Type inference | `read_csv(..., dtypes={...})` or cast in `SELECT` |
| Huge files | `LIMIT` while exploring; consider `WHERE` on ingest |
| XLSX fails | Confirm `excel` extension loaded |

---

## After bronze → go to silver

Once data is in bronze, use [`ingest-data-silver`](../ingest-data-silver/SKILL.md)
to clean, deduplicate, normalize, or join tables.
