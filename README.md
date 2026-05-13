# Datacyber (DataSyn)

Monorepo for an **AI-assisted analytics stack** on open and public data: a DuckDB warehouse, Dagster pipelines, HTTP MCP tool servers (DuckDB SQL, MinIO object storage, Dagster scaffolding), and an agent plus web UI.

## Goals

Make it easier to **discover, load, and reason about** public datasets with reproducible pipelines and clear metadata—without treating opaque automation as a substitute for auditability.

## Repository layout

| Path | Role |
|------|------|
| `agent/` | Brain service (FastAPI), MCP clients, orchestration |
| `ui/` | Vite frontend |
| `mcp.json` | HTTP MCP server URLs used by the brain (Docker service names on `infra-datasynk`) |
| `compose.env` | Comment-only template for brain/Docker env (copy ideas into root `.env`) |
| `docker-compose.yaml` | Root stack: brain, UI, Jupyter, optional Telegram (expects `infra-datasynk`) |
| `AGENTS.md` | Warehouse and MCP behavior for the agent (authoritative constraints) |
| `skills/` | Deep Agents `SKILL.md` playbooks (ingest, catalog, analysis) |
| `data-local/` | **Local data mirror** for DuckDB paths (gitignored; see `.gitignore`) |

### Infra stacks (`infra/`)

Each stack has a **`docker-compose.yaml`** at its root and **subfolders per image/service**:

| Stack | Compose file | Subfolders (images / config) |
|-------|----------------|------------------------------|
| **DuckDB** | `infra/duckdb/docker-compose.yaml` | `warehouse/` — warehouse container (`Dockerfile`, `init_db.py`); `mcp/` — DuckDB MCP; `ui/` — DuckDB Local UI (profile `ui`) |
| **Object storage** | `infra/object-storage/docker-compose.yaml` | `minio/` — MinIO server image; `mcp/` — storage MCP (S3-style tools) |
| **Dagster** | `infra/dagster/docker-compose.yaml` | `runtime/` — webserver + daemon image, `dagster.yaml`, `workspace.yaml`; `postgres/` — metadata Postgres; `mcp/` — Dagster MCP + **`mcp/dagster-code/projects/`** (code locations); `mcp/dagster-code/projects/datasyn/` — active code location and gRPC image build context |

Other optional stacks under `infra/` (each with its own compose file): **`langfuse/`**, **`litellm/`**, **`telegram_bot/`**.

| Path | Role |
|------|------|
| `infra/dagster/mcp/dagster-code/projects/datasyn/` | Dagster definitions (bronze assets, jobs, schedules); **`Dockerfile`** builds `dagster_user_code_image` |
| `infra/dagster/mcp/dagster-code/projects/datasyn/scripts/r/` | R/shell helpers (e.g. UCA / MinIO) |

## Quick start

1. **Shared Docker network and volumes** (once per machine):

   ```bash
   make bootstrap-infra-primitives
   ```

   Creates network **`infra-datasynk`** and volumes **`duckdb_data`**, **`storage`**.

2. **Infra (recommended)** — object storage, DuckDB + MCP, Dagster (Postgres, user code, webserver, daemon) + MCP, plus optional Langfuse and Telegram stacks as defined in the `Makefile`:

   ```bash
   make infra-up
   ```

   To build images first: `make infra-build`.

3. **Agent + UI** (after infra is healthy):

   ```bash
   make agent-up
   ```

   Or full stack in one go: `make stack-up` (same as `infra-up` then `agent-up`).

4. **Local development** (brain on the host with hot reload, UI on Vite):

   ```bash
   make mcp-up    # or rely on ``make infra-up`` already running MCP
   make agent-dev
   ```

   The brain maps `mcp.json` hostnames (`duckdb-mcp`, `dagster-mcp`, `storage-mcp`) to `127.0.0.1` on ports **8040**, **8043**, **8044** when not running inside Docker. See `compose.env` for details.

### Compose-only equivalent

If you prefer not to use `make`:

```bash
docker network create infra-datasynk 2>/dev/null || true
docker volume create duckdb_data 2>/dev/null || true
docker volume create storage 2>/dev/null || true

docker compose -f infra/object-storage/docker-compose.yaml up -d
docker compose -f infra/duckdb/docker-compose.yaml up -d
docker compose -f infra/dagster/docker-compose.yaml up -d
docker compose up -d
```

Order matters: object storage before services that need MinIO; DuckDB and Dagster can follow (Dagster user code expects the warehouse volume and optional `data-local` bind). Root `docker-compose.yaml` lists the same order in its header comments.

### MCP-only slice

To start just the three MCP endpoints (and their hard dependencies: `minio`, `duckdb`, `dagster-mcp`):

```bash
make mcp-up
```

Useful when you already have other infra down but still want tools for `make agent-dev`.

### DuckDB Local UI (optional)

The warehouse file allows only one writer. The UI holds a long-lived connection, so it is behind compose **profile `ui`**:

```bash
make infra-duckdb-ui-up
# or: docker compose -f infra/duckdb/docker-compose.yaml --profile ui up -d
```

Stop the UI before heavy MCP ingest if you see file lock errors: `make infra-duckdb-ui-down`.

## Configuration

- **Per-stack env**: copy `*.env.example` where present, e.g. `infra/object-storage/.env.example` → `infra/object-storage/.env`, and maintain `infra/dagster/.env`, `infra/duckdb/.env` as needed.
- **DuckDB MCP**: optional `infra/duckdb/mcp/.env` (see `infra/duckdb/mcp/.env.example`); compose treats it as optional.
- **Dagster code-location image**: `make infra-up` / `make infra-build` run `docker build -t dagster_user_code_image:latest infra/dagster/mcp/dagster-code/projects/datasyn`.
- **Brain / root**: `compose.env` is a comment template; for Docker, merge with root `.env` as in `docker-compose.yaml`. **`mcp.json`** at the repo root drives MCP HTTP URLs.

## Security and `.gitignore`

**Do not commit:**

- `.env` / `.env.*` (except allowed `*.env.example` patterns)
- Private keys: **`*.pem`**, `*.p12`, `*.pfx`, SSH key material
- Local data and DB files: `data-local/`, `*.duckdb`, etc.

The root **`.gitignore`** applies across the tree; nested stacks add their own rules. Generated or local artifacts under **`infra/dagster/mcp/dagster-code/projects/`** follow **`projects/.gitignore`**.

If a private key was ever committed, **rotate the key** and remove it from history (e.g. `git filter-repo` or BFG) on any shared remote.

## MCP and warehouse

Runtime tool names and constraints for DuckDB, object storage, and Dagster are summarized in **`AGENTS.md`** (and injected at runtime for the agent). Use **`make help`** for all Makefile targets.
