---
name: analyze-indec-eph-individual
description: >-
  Analyze and summarize the DuckDB table `gold.indec_eph_usu_individual` using
  `duckdb_execute_query`, mapping each column to the dictionary rows in
  `silver.indec_mercado_laboral_variables` (`campo`). Use when the user asks to
  analyze EPH individual microdata, summarize variables, or return findings in a
  results table.
---

# Analisis de `gold.indec_eph_usu_individual`

Use this skill for requests about EPH individual-level data (`usu_individual`).
Goal: produce a concise summary with evidence and a final markdown table.

## Tools

- `duckdb_execute_query` for all SQL (one statement per call).
- Optional `duckdb_get_schema` for quick schema discovery.

Do not use deprecated tool names.

## Required workflow

Copy this checklist and execute in order:

```text
- [ ] 1) Confirm table exists and get row count
- [ ] 2) Build column inventory from information_schema
- [ ] 3) Join with silver dictionary (campo -> descripcion)
- [ ] 4) Compute data quality/coverage summary
- [ ] 5) Return a concise narrative + markdown results table
```

### 1) Confirm table and volume

```sql
SELECT
  COUNT(*) AS rows_total,
  COUNT(DISTINCT CODUSU || '|' || COMPONENTE || '|' || ANO4 || '|' || TRIMESTRE) AS approx_pk_distinct
FROM gold.indec_eph_usu_individual;
```

### 2) Inventory columns

```sql
SELECT
  ordinal_position,
  column_name,
  data_type
FROM information_schema.columns
WHERE table_schema = 'gold'
  AND table_name = 'indec_eph_usu_individual'
ORDER BY ordinal_position;
```

### 3) Map columns to dictionary rows

```sql
WITH cols AS (
  SELECT ordinal_position, column_name, data_type
  FROM information_schema.columns
  WHERE table_schema = 'gold'
    AND table_name = 'indec_eph_usu_individual'
)
SELECT
  c.ordinal_position,
  c.column_name AS campo,
  c.data_type AS tipo_sql,
  s.tipo AS tipo_diccionario,
  s.longitud,
  s.descripcion
FROM cols c
LEFT JOIN silver.indec_mercado_laboral_variables s
  ON s.campo = c.column_name
ORDER BY c.ordinal_position;
```

### 4) Coverage + quality summary

```sql
WITH cols AS (
  SELECT column_name
  FROM information_schema.columns
  WHERE table_schema = 'gold'
    AND table_name = 'indec_eph_usu_individual'
),
mapped AS (
  SELECT
    c.column_name,
    s.descripcion
  FROM cols c
  LEFT JOIN silver.indec_mercado_laboral_variables s
    ON s.campo = c.column_name
)
SELECT
  COUNT(*) AS total_columns,
  COUNT(*) FILTER (WHERE descripcion IS NOT NULL AND TRIM(descripcion) <> '') AS mapped_columns,
  COUNT(*) FILTER (WHERE descripcion IS NULL OR TRIM(descripcion) = '') AS unmapped_columns,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE descripcion IS NOT NULL AND TRIM(descripcion) <> '') / NULLIF(COUNT(*), 0),
    2
  ) AS mapped_pct
FROM mapped;
```

## Output format (mandatory)

Return:

1. A short summary (3-6 bullets max).
2. One markdown table named `Resultados` with at least:
   - `rows_total`
   - `approx_pk_distinct`
   - `total_columns`
   - `mapped_columns`
   - `unmapped_columns`
   - `mapped_pct`
3. If there are unmapped columns, add a second markdown table:
   - `column_name`
   - `data_type`
   - `suggested_action` (`re-run variables job` or `manual dictionary completion`)

Keep the answer concise and evidence-based.
