---
name: ingest-data-gold
description: >-
  Aggregate, summarize, and create analysis-ready datasets from silver into
  the gold schema. Third layer of the medallion pattern — business metrics,
  KPIs, daily reports, dashboards. Use when the user asks for aggregated
  views, summaries, rankings, or report-ready tables.
---

# Ingest data — Gold (analytics layer)

**Zone:** Gold — `gold.*` schema.
**Source:** `silver.*` tables (cleaned, joined, validated data).
**Goal:** aggregate, summarize, compute metrics. Ready for reports.

---

## Start here — analyze before you act

1. **What is the source?** → `silver.*` tables (clean, structured data)
2. **What aggregation is needed?** → GROUP BY? window functions? rankings? time series?
3. **Confirm zone** → yes, this is **gold** — analytics-ready datasets

---

## Workflow

1. **Verify silver source** — `SELECT COUNT(*), MIN(date), MAX(date) FROM silver.table`
2. **Define the metric** — what question does this gold table answer?
3. **Create schema** — `CREATE SCHEMA IF NOT EXISTS gold`
4. **Write aggregation SQL** — GROUP BY, window functions, CTEs
5. **Create gold table** — `CREATE OR REPLACE TABLE gold.{name} AS ...`
6. **Validate** — row counts, value ranges, sanity checks

---

## Common gold transformations

### Daily aggregation

```sql
CREATE OR REPLACE TABLE gold.daily_summary AS
SELECT
    fecha,
    COUNT(*) AS total,
    COUNT(DISTINCT categoria) AS categorias,
    SUM(monto) AS monto_total
FROM silver.transactions
GROUP BY fecha
ORDER BY fecha;
```

### Rankings

```sql
CREATE OR REPLACE TABLE gold.top_entities AS
SELECT
    nombre,
    tipo,
    COUNT(*) AS apariciones,
    RANK() OVER (ORDER BY COUNT(*) DESC) AS ranking
FROM silver.entidades_flat
GROUP BY nombre, tipo
QUALIFY ranking <= 20;
```

### Time series

```sql
CREATE OR REPLACE TABLE gold.weekly_trend AS
SELECT
    DATE_TRUNC('week', fecha_publicacion) AS semana,
    seccion,
    COUNT(*) AS avisos
FROM silver.entidades_flat
GROUP BY semana, seccion
ORDER BY semana;
```

### Pivot / cross-tab

```sql
CREATE OR REPLACE TABLE gold.categoria_diaria AS
SELECT
    fecha,
    COUNT(*) FILTER (WHERE tipo = 'empresa') AS empresas,
    COUNT(*) FILTER (WHERE tipo = 'persona') AS personas
FROM silver.entidades_flat
GROUP BY fecha
ORDER BY fecha;
```

### Joining metrics from multiple silver tables

```sql
CREATE OR REPLACE TABLE gold.empresa_metricas AS
SELECT
    e.nombre,
    e.fecha_publicacion,
    COUNT(ev.entidad_id) AS total_socios,
    e.seccion
FROM silver.empresas e
LEFT JOIN silver.vinculos ev ON e.aviso_id = ev.aviso_id
GROUP BY e.nombre, e.fecha_publicacion, e.seccion;
```

---

## Validation (via MCP)

```sql
-- Row count
SELECT COUNT(*) FROM gold.daily_summary;

-- Sanity checks
SELECT MIN(fecha), MAX(fecha) FROM gold.daily_summary;
SELECT * FROM gold.daily_summary WHERE total < 0;  -- no negatives

-- Sample
SELECT * FROM gold.daily_summary ORDER BY fecha DESC LIMIT 10;

-- Compare with source
SELECT COUNT(*) FROM silver.transactions;
SELECT SUM(monto_total) FROM gold.daily_summary;  -- should match silver
```

---

## Example: Boletín Oficial

```sql
CREATE SCHEMA IF NOT EXISTS gold;

-- Daily constitution counts
CREATE OR REPLACE TABLE gold.daily_constituciones AS
SELECT
    fecha_publicacion,
    COUNT(*) AS total_avisos,
    COUNT(DISTINCT empresa) AS empresas_unicas
FROM silver.entidades_flat
GROUP BY fecha_publicacion
ORDER BY fecha_publicacion;

-- Top sectors
CREATE OR REPLACE TABLE gold.sectores_top AS
SELECT
    seccion,
    COUNT(*) AS avisos,
    COUNT(DISTINCT fecha_publicacion) AS dias_activos
FROM silver.entidades_flat
GROUP BY seccion
ORDER BY avisos DESC;
```

---

## After gold → reports

Gold tables feed directly into reports. Use [`statistical-report`](../statistical-report/SKILL.md),
[`graph-analysis`](../graph-analysis/SKILL.md), or [`sentiment-analysis`](../sentiment-analysis/SKILL.md)
to produce final outputs.
