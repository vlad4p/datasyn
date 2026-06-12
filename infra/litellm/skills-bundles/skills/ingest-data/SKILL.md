---
name: ingest-data
description: >-
  Entry point for the medallion architecture (bronze → silver → gold).
  Routes ingestion requests to the correct zone. Use when the user asks
  to ingest, import, load, clean, join, or prepare data for analysis.
---

# Ingest data (medallion architecture)

Data flows through three quality zones. Start each request by analyzing which
zone fits the source and goal.

```
landing/ ──→ bronze ──→ silver ──→ gold ──→ reports
  raw         raw       clean      ready
  files       SQL        joins     aggregates
```

| Zone | Schema | Purpose | Source | Skill |
|------|--------|---------|--------|-------|
| 🟤 **Bronze** | `bronze.*` | Raw ingest, preserve originals | `data/landing/` files, scrapes | [`ingest-data-bronze`](../ingest-data-bronze/SKILL.md) |
| ⚪ **Silver** | `silver.*` | Clean, dedupe, normalize, join | `bronze.*` tables | [`ingest-data-silver`](../ingest-data-silver/SKILL.md) |
| 🟡 **Gold** | `gold.*` | Aggregated, analysis‑ready datasets | `silver.*` tables | [`ingest-data-gold`](../ingest-data-gold/SKILL.md) |

## Decision flow

1. **What is the source?** → landing file? → **bronze** · existing table? → **silver** or **gold**
2. **What transformation is needed?** → none → **bronze** · clean/join → **silver** · aggregate/summarize → **gold**
3. **Route to the right skill** → read that skill's workflow and templates

## Example scenarios

| User says | Zone | Skill |
|-----------|------|-------|
| "Ingestá este CSV" | Bronze | `ingest-data-bronze` |
| "Scrapeá y guardá en la DB" | Bronze | `ingest-data-bronze` |
| "Limpiá duplicados y normalizá nombres" | Silver | `ingest-data-silver` |
| "Creá una tabla uniendo empresas con socios" | Silver | `ingest-data-silver` |
| "Creá un dataset para reportes diarios" | Gold | `ingest-data-gold` |
| "Agrupá por sector y calculá totales" | Gold | `ingest-data-gold` |

## General rules (all zones)

- **SQL via MCP** for queries; `db.py run-sql` for DDL (CREATE TABLE, INSERT)
- Never mutate landing files — they are the source of truth
- Always validate: `COUNT(*)`, `DESCRIBE`, sample rows after each step
- Each sub-skill starts by analyzing the source and confirming the correct zone
