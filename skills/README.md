# Skills

Task workflows for AI assistants. **No Python scripts** — the agent runs DuckDB SQL and writes outputs following these guides.

## Configure in your AI assistant

Copy or link this folder into your tool’s skills directory:

| Tool | Typical path |
|------|----------------|
| **Cursor** | `.cursor/skills/` → symlink: `ln -sfn "$(pwd)/skills" .cursor/skills` |
| **Claude Code** | `.claude/skills/` or project skills setting |
| **Other** | Follow your client’s docs for project-level `SKILL.md` folders |

**First-time setup:** copy the bootstrap prompt from [`README.md`](../README.md) or [`README.es.md`](../README.es.md).

**Ongoing behavior:** [`AGENTS.md`](../AGENTS.md), not here.

## Catalog

### Data ingestion (medallion pattern)

| Skill | Zone | When to use |
|-------|------|-------------|
| [`ingest-data`](ingest-data/SKILL.md) | Entry point | Route to the right zone |
| [`ingest-data-bronze`](ingest-data-bronze/SKILL.md) | `bronze.*` | Raw files → DuckDB (CSV, JSON, Parquet, XLSX…) |
| [`ingest-data-silver`](ingest-data-silver/SKILL.md) | `silver.*` | Clean, dedupe, normalize, join from bronze |
| [`ingest-data-gold`](ingest-data-gold/SKILL.md) | `gold.*` | Aggregate, summarize, KPIs from silver |

### Analysis & reports

| Skill | When to use |
|-------|-------------|
| [`analyze-langfuse-trace`](analyze-langfuse-trace/SKILL.md) | Post-mortem Langfuse trace JSON (latency, tokens, delegation, improvements) |
| [`graph-ingest`](graph-ingest/SKILL.md) | Build graph tables (vertices & edges) from entity-link data |
| [`graph-analysis`](graph-analysis/SKILL.md) | Network analysis: centrality, communities, density reports |
| [`interactive-graph-reports`](interactive-graph-reports/SKILL.md) | HTML graph visualizations (vis.js + React + Chart.js) |
| [`statistical-report`](statistical-report/SKILL.md) | EDA and reports (many output formats) |
| [`sentiment-analysis`](sentiment-analysis/SKILL.md) | Text tone / framing reports |

### Data collection & setup

| Skill | When to use |
|-------|-------------|
| [`web-scraping`](web-scraping/SKILL.md) | Fetch data to `data/landing/` |
| [`create-table`](create-table/SKILL.md) | Schema design |
| [`create-python-script`](create-python-script/SKILL.md) | Optional code in `scripts/python/` |
| [`configure-duckdb-mcp`](configure-duckdb-mcp/SKILL.md) | MCP server setup (Cursor, VS Code, Kilo Code) |
| [`setup-uv`](setup-uv/SKILL.md) | Python environment |
