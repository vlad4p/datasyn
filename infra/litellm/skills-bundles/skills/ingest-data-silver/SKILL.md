---
name: ingest-data-silver
description: >-
  Clean, deduplicate, normalize, and join data from bronze into the silver
  schema. Second layer of the medallion pattern — structured, validated,
  ready for analysis. Use when the user asks to clean data, remove duplicates,
  normalize names, join tables, or create refined datasets.
---

# Ingest data — Silver (clean layer)

**Zone:** Silver — `silver.*` schema.
**Source:** `bronze.*` tables (already ingested raw data).
**Goal:** clean, deduplicate, normalize, join. Structured and validated.

---

## Start here — analyze before you act

1. **What is the source?** → check: `SELECT * FROM bronze.my_table LIMIT 3`
2. **What needs cleaning?** → duplicates? nulls? inconsistent types? need a join?
3. **Confirm zone** → yes, this is **silver** — transforming bronze into clean data

---

## Workflow

1. **Profile the bronze source** — `COUNT(*)`, `DESCRIBE`, `SUMMARIZE`, null counts
2. **Identify issues** — duplicates, inconsistent formats, missing values, needed joins
3. **Create schema** — `CREATE SCHEMA IF NOT EXISTS silver`
4. **Write transformation SQL** — SELECT with cleaning logic
5. **Create silver table** — `CREATE OR REPLACE TABLE silver.{name} AS ...`
6. **Validate** — `COUNT(*)`, `DESCRIBE`, sample rows, compare with bronze row counts

---

## Common silver transformations

### Deduplicate

```sql
CREATE OR REPLACE TABLE silver.deduped AS
SELECT DISTINCT * FROM bronze.raw_table;

-- Or by specific columns
CREATE OR REPLACE TABLE silver.deduped AS
SELECT * FROM bronze.raw_table
QUALIFY ROW_NUMBER() OVER (PARTITION BY key_col ORDER BY scraped_at DESC) = 1;
```

### Normalize / clean text

```sql
CREATE OR REPLACE TABLE silver.clean AS
SELECT
    id,
    TRIM(UPPER(nombre)) AS nombre_normalizado,
    CAST(fecha AS DATE) AS fecha,
    REGEXP_REPLACE(contenido, '\s+', ' ', 'g') AS contenido_clean
FROM bronze.raw_table
WHERE nombre IS NOT NULL
  AND LENGTH(TRIM(nombre)) > 0;
```

### Join tables

```sql
CREATE OR REPLACE TABLE silver.joined AS
SELECT
    a.*,
    b.nombre AS categoria_nombre
FROM bronze.facts a
LEFT JOIN bronze.categories b ON a.categoria_id = b.id;
```

### Flatten / unnest structs

```sql
CREATE OR REPLACE TABLE silver.flattened AS
SELECT
    id,
    UNNEST(items) AS item
FROM bronze.nested_table;
```

### Type casting

```sql
CREATE OR REPLACE TABLE silver.typed AS
SELECT
    id::INTEGER AS id,
    nombre::VARCHAR AS nombre,
    CAST(REPLACE(monto, '$', '') AS DECIMAL(12,2)) AS monto,
    fecha::DATE AS fecha
FROM bronze.raw_table;
```

---

## Validation (via MCP)

```sql
-- Compare row counts
SELECT 'bronze' AS layer, COUNT(*) FROM bronze.raw_table
UNION ALL
SELECT 'silver', COUNT(*) FROM silver.clean;

-- Check schema
DESCRIBE silver.clean;

-- Sample
SELECT * FROM silver.clean LIMIT 5;

-- Check for remaining nulls
SELECT COUNT(*) AS null_keys FROM silver.clean WHERE key_col IS NULL;
```

---

## Example: entities from Boletín Oficial

```sql
-- Bronze → Silver: extract entities from raw avisos
CREATE SCHEMA IF NOT EXISTS silver;

CREATE OR REPLACE TABLE silver.entidades_flat AS
SELECT
    u.id AS aviso_id,
    u.titulo AS empresa,
    u.fecha_publicacion,
    u.seccion
FROM bronze.boletin_oficial_avisos,
LATERAL (SELECT UNNEST(j.avisos)) AS u;

-- Validate
SELECT COUNT(*) FROM silver.entidades_flat;
SELECT * FROM silver.entidades_flat LIMIT 3;
```

---

## After silver → go to gold

Once data is clean and structured, use [`ingest-data-gold`](../ingest-data-gold/SKILL.md)
to aggregate, summarize, or create analysis-ready datasets.
