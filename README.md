# Datacyber (DataSyn)

Monorepo for an **AI-assisted analytics stack** on open and public data: a DuckDB warehouse, Dagster bronze assets, HTTP MCP servers (DuckDB, object storage, Dagster helpers), and an agent + web UI.

## Goals

Make it easier to **discover, load, and reason about** public datasets with reproducible pipelines and clear metadata—without treating opaque automation as a substitute for auditability.

## Repository layout

| Path | Role |
|------|------|
| `agent/` | Brain service (FastAPI), MCP clients, orchestration |
| `infra/duckdb/mcp/` | DuckDB warehouse MCP (`duckdb-mcp` in Compose) |
| `infra/dagster/mcp/` | Dagster scaffold/deploy MCP (`dagster-mcp`) |
| `infra/object-storage/mcp/` | MinIO/S3 browser MCP (`storage-mcp`) |
| `infra/dagster/dagster-code/projects/datasyn/` | Dagster code location (bronze assets, jobs, schedules) |
| `infra/` | Docker stacks (object storage, DuckDB, Dagster, Langfuse, etc.) |
| `skills/` | Deep Agents `SKILL.md` playbooks (ingest, catalog, analysis) |
| `infra/dagster/dagster-code/projects/datasyn/scripts/r/` | R/shell helpers for census/UCA (REDATAM export, MinIO upload) |
| `ui/` | Vite frontend |
| `data-local/` | **Local data mirror** (gitignored; see `.gitignore`) |
| `AGENTS.md` | Instructions for the warehouse/agent runtime |

## Quick start

1. One-time shared Docker network/volumes: `make bootstrap-infra-primitives`
2. Bring up infra (object storage, DuckDB + MCP, Dagster + MCP, …): `make infra-up`  
   (MCP-only without the full Dagster stack: `make mcp-up`)
3. Local dev (brain + UI): `make agent-dev`  
   Use `make help` for infra, agent, and full-stack targets.

Compose order and options are documented in `docker-compose.yaml` and the `infra/*/docker-compose.yaml` stacks (DuckDB, object storage, Dagster include MCP services).

## Configuration

- Use **`.env.example`** files where provided; copy to **`.env`** and set real values locally.
- **`compose.env`** in the repo root is a **comment-only** template for Docker/brain variables (no secrets checked in).
- MCP URLs for local development are typically configured via **`mcp.json`** (see `compose.env` header comments).

## Security and `.gitignore`

**Do not commit:**

- `.env` / `.env.*` (except allowed `*.env.example` patterns)
- Private keys: **`*.pem`**, `*.p12`, `*.pfx`, SSH key material
- Local data and DB files: `data-local/`, `*.duckdb`, etc.

The root **`.gitignore`** applies across the tree; nested stacks (e.g. `infra/dagster/`, `infra/langfuse/`) add their own rules. Generated code under **`infra/dagster/dagster-code/projects/`** uses **`projects/.gitignore`** for `.env` and Python artifacts.

If a private key was ever committed, **rotate the key** and remove it from history (e.g. `git filter-repo` or BFG) on any shared remote.

## MCP and warehouse

Runtime tool names and constraints for DuckDB, object storage, and Dagster are summarized in **`AGENTS.md`** (and injected at runtime for the agent).
