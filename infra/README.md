# Infra Docker stacks

Each service under `infra/*` has its **own Makefile**. Shared `ENVIRONMENT` / `bootstrap` helpers: [`deploy.mk`](deploy.mk) (included by each stack).

## Quick start (local dev)

```bash
make -C infra/object-storage bootstrap   # once: network + volumes
make -C infra/object-storage up
make -C infra/duckdb up
make -C infra/dagster up
make agent-dev                           # repo root — brain + UI on host
```

MCP servers (if not already running via `up`):

```bash
make -C infra/object-storage mcp-up
make -C infra/duckdb mcp-up
```

## Stacks

| Directory | Role | Help |
|-----------|------|------|
| [`object-storage/`](object-storage/) | MinIO + storage-mcp | `make -C infra/object-storage help` |
| [`duckdb/`](duckdb/) | Warehouse + duckdb-mcp (Quack server `:9494`, MCP `:8040`) | `make -C infra/duckdb help` |
| [`dagster/`](dagster/) | Dagster runtime | `make -C infra/dagster help` |
| [`agent/`](agent/) | Brain + UI containers | `make -C infra/agent help` |
| [`litellm/`](litellm/) | LLM proxy | `make -C infra/litellm help` |
| [`langfuse-deploy/`](langfuse-deploy/) | Optional tracing | `make -C infra/langfuse-deploy help` |
| [`distribution/`](distribution/) | OCI registry + `publish` | `make -C infra/distribution help` |

**Env templates:** repo `.env.example` / `.env.deploy.example` / `mcp.json.example`; per-stack `*/.env.example` (Dagster: run `make patch-runtime` after edits). Fleet: `ia-infra-recipe/fleet.env` + `provision-vm.sh`.

## Prod-like full stack (Docker)

```bash
make -C infra/object-storage up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/duckdb up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/dagster up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/agent up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
```

Publish all images: `make -C infra/distribution publish ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=…`

See [`INSTALL.md`](../INSTALL.md) for full deployment guide.

## Multi-VM layout (Proxmox fleet)

| VM | Stack | Warehouse access |
|----|-------|------------------|
| VM1 | `infra/duckdb` | `duckdb-mcp` owns `warehouse.duckdb` RW + **Quack** (`quack:0.0.0.0:9494`) + MCP (`:8040`) |
| VM2 | `infra/object-storage` | MinIO; bronze sources read via DuckDB **httpfs** `s3://` URLs |
| VM3 | `infra/dagster` | Dagster attaches warehouse via **`QUACK_URI`** (no `duckdb_data` volume) |

Set matching **`QUACK_TOKEN`** on VM1 (`infra/duckdb/mcp/.env`) and VM3 (`infra/dagster/.env`).
