# Datacyber (DataSyn)

Monorepo for an **AI-assisted analytics stack** on open and public data: a DuckDB warehouse, Dagster bronze assets, HTTP MCP servers (DuckDB, scrapers, Dagster helpers), and an agent + web UI.

## Goals

Make it easier to **discover, load, and reason about** public datasets with reproducible pipelines and clear metadata—without treating opaque automation as a substitute for auditability.

## Repository layout

| Path | Role |
|------|------|
| `agent/` | Brain service (FastAPI), MCP clients, orchestration |
| `mcp_servers/` | `duckdb-mcp`, `scrapper-mcp`, `dagster-mcp` and shared compose |
| `mcp_servers/dagster-mcp/projects/datasyn/` | Dagster code location (bronze assets, jobs, schedules) |
| `infra/` | Optional Docker stacks (object storage, DuckDB, Dagster, Langfuse, etc.) |
| `skills/` | Deep Agents `SKILL.md` playbooks (ingest, catalog, analysis) |
| `mcp_servers/dagster-mcp/projects/datasyn/scripts/r/` | R/shell helpers for census/UCA (REDATAM export, MinIO upload) |
| `ui/` | Vite frontend |
| `data-local/` | **Local data mirror** (gitignored; see `.gitignore`) |
| `AGENTS.md` | Instructions for the warehouse/agent runtime |

## Quick start

1. One-time shared Docker network/volumes: `make bootstrap-infra-primitives`
2. Bring up MCP services: `make mcp-up`
3. Local dev (brain + UI): `make agent-dev`  
   Use `make help` for infra, agent, and full-stack targets.

Compose order and options are documented in `docker-compose.yaml` and `mcp_servers/docker-compose.yaml`.

## Configuration

- Use **`.env.example`** files where provided; copy to **`.env`** and set real values locally.
- **`compose.env`** in the repo root is a **comment-only** template for Docker/brain variables (no secrets checked in).
- MCP URLs for local development are typically configured via **`mcp.json`** (see `compose.env` header comments).

## Security and `.gitignore`

**Do not commit:**

- `.env` / `.env.*` (except allowed `*.env.example` patterns)
- Private keys: **`*.pem`**, `*.p12`, `*.pfx`, SSH key material
- Local data and DB files: `data-local/`, `*.duckdb`, etc.

The root **`.gitignore`** applies across the tree; nested stacks (e.g. `infra/dagster/`, `infra/langfuse/`) add their own rules. Generated code under **`mcp_servers/dagster-mcp/projects/`** uses **`projects/.gitignore`** for `.env` and Python artifacts.

If a private key was ever committed, **rotate the key** and remove it from history (e.g. `git filter-repo` or BFG) on any shared remote.

## MCP and warehouse

Runtime tool names and constraints for DuckDB, scrapers, and Dagster are summarized in **`AGENTS.md`** (and injected at runtime for the agent).
