---
name: statistical-report
description: >-
  Generate analysis reports from DuckDB tables using SQL via MCP only (no Python
  report scripts, no direct Python DuckDB connections). Supports markdown EDA,
  executive brief, JSON metrics, CSV extracts, and HTML summary.
  Use for profiling, EDA, data quality, or report requests.
---

# Generate reports (skill — SQL via MCP only)

Do **not** run `make report` or Python report modules. Query with DuckDB via MCP
(`uv run python scripts/python/db.py run-sql "SQL..."`), then **write the file** under `reports/`.

## Prerequisites

- Table exists in DuckDB (`SHOW TABLES`)
- Output directory: `reports/` (gitignored content)

## Workflow

1. **Clarify format** — ask or infer from user request (see matrix)
2. **Profile in SQL** — `COUNT`, `DESCRIBE`, `SUMMARIZE`, domain queries
3. **Draft report** — markdown/HTML/JSON/CSV per template
4. **Save** — `reports/{table}_{format}_{YYYYMMDD}.md` (adjust extension)

## Output format matrix

| Format | Extension | Best for | Agent action |
|--------|-----------|----------|--------------|
| **Markdown EDA** | `.md` | Full statistical profile | SQL → structured sections below |
| **Executive brief** | `.md` | 1-page decision summary | Top metrics + 3–5 bullet findings |
| **JSON metrics** | `.json` | Dashboards / downstream tools | Export key scalars + small tables as JSON |
| **CSV profile** | `.csv` | Spreadsheet handoff | `COPY (SUMMARIZE t) TO 'reports/...'` |
| **HTML summary** | `.html` | Readable shareable snapshot | Minimal HTML + embedded tables |
| **Sentiment / text** | `.md` | News, articles | Use skill `sentiment-analysis` instead |

## Core SQL (all formats)

```sql
SELECT COUNT(*) AS row_count FROM {table};
DESCRIBE {table};
SUMMARIZE {table};
```

### Extra profiling

```sql
-- Null-heavy columns
SELECT * FROM (SUMMARIZE {table}) WHERE null_percentage > 0;

-- Top categories
SELECT col, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

-- Date span
SELECT MIN(date_col), MAX(date_col) FROM {table};
```

### Export helpers

```sql
-- CSV slice
COPY (SELECT * FROM {table} LIMIT 1000) TO 'reports/{table}_sample.csv' (HEADER, DELIMITER ',');

-- JSON metrics file (example: row count only)
COPY (SELECT COUNT(*) AS row_count FROM {table}) TO 'reports/{table}_metrics.json';
```

## Template: Markdown EDA (`.md`)

```markdown
# Report: `{table}`

Generated: {date}
Format: markdown_eda

## Executive summary
[2–3 sentences with numbers]

## Overview
- Rows: …
- Columns: …

## Schema
[DESCRIBE as table]

## Summary statistics
[SUMMARIZE highlights]

## Data quality
- Nulls, duplicates, outliers

## Findings
- …

## Limits
- What was not checked; sampling bias

## Methods
- SQL used (brief)
```

## Template: Executive brief (`.md`)

```markdown
# Executive brief: `{table}`

**Bottom line:** …

| Metric | Value |
|--------|-------|
| Rows | … |

## Findings
1. …
2. …

## Recommended next steps
- …
```

## Template: JSON metrics (`.json`)

```json
{
  "table": "{table}",
  "generated": "{iso_date}",
  "format": "json_metrics",
  "row_count": 0,
  "columns": [],
  "quality_flags": [],
  "notes": ""
}
```

Fill with query results; keep files small.

## Template: HTML summary (`.html`)

Minimal single-file HTML: `<h1>`, one `<table>` for schema, one for top summary stats, footer with generation time. No external CSS required.

## File naming

```
reports/{table}_eda_{YYYYMMDD}.md
reports/{table}_executive_{YYYYMMDD}.md
reports/{table}_metrics_{YYYYMMDD}.json
reports/{table}_sample_{YYYYMMDD}.csv
reports/{table}_summary_{YYYYMMDD}.html
```

## Persona

**Expert data analyst**: every claim tied to a query result; state limits; suggest follow-up analyses.
