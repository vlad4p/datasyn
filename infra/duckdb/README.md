# DuckDB warehouse + MCP + Quack

## Services

| Service | Role |
|---------|------|
| `duckdb` | One-shot init: creates `warehouse.duckdb` and medallion schemas on `duckdb_data` volume |
| `duckdb-mcp` | **Single RW owner** of `warehouse.duckdb`; FastMCP HTTP on `:8040`; **Quack** remote protocol on `:9494` |
| `duckdb-ui` | Optional browser UI (profile `ui`) — conflicts with `duckdb-mcp` on the same DB file |

## Quack (remote warehouse)

[DuckDB Quack](https://duckdb.org/docs/current/quack/overview) exposes the warehouse over HTTP. Dagster and other clients attach with:

```sql
ATTACH 'quack:host:9494' AS warehouse (TYPE quack, TOKEN '…', DISABLE_SSL true);
USE warehouse;
```

Configure server in `mcp/.env` (`QUACK_BIND_URI`, `QUACK_TOKEN`). Clients need the same token.

## MinIO (httpfs)

`duckdb-mcp` configures an S3 secret for MinIO when `MINIO_ENDPOINT` and credentials are set. Dagster clients configure the same secret locally to `read_csv_auto('s3://…')` before writing bronze tables via Quack.

## Quick start

```bash
make -C infra/duckdb mcp-up   # duckdb init + duckdb-mcp (:8040, :9494)
```

Copy `mcp/.env.example` → `mcp/.env` and align `QUACK_TOKEN` with `infra/dagster/.env`.
