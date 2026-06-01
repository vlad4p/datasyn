# Security

## Reporting vulnerabilities

If you find a security issue, please report it privately (GitHub Security Advisories or direct contact with maintainers). Do not open a public issue for undisclosed vulnerabilities.

## Local development defaults

This repository ships **development-only** credentials in Docker Compose and `.env.example` files:

- MinIO: `minioadmin` / `minioadmin123`
- Dagster Postgres: `postgres_user` / `postgres_password`
- LiteLLM Postgres: `litellm` / `litellm`
- Langfuse example: `admin@example.com` / `datasyn-local`

**Never use these defaults in production.** Rotate all secrets, bind services to private networks, and enable OAuth (`OAUTH_*` in `.env.example`) before exposing the brain API to the internet.

## Brain API and auth

- OAuth is **off** until `OAUTH_SESSION_SECRET` and at least one provider are configured.
- When auth is enabled, only `GET /health` and `/auth/*` are public; other `/health/*` routes require a session.
- MCP servers (`duckdb-mcp`, `storage-mcp`) execute SQL and object-storage operations — do not publish their ports without network controls.

## Secrets in git

Do not commit `.env`, keys, or data under `data-local/`. Run a secret scanner on git history before the first public release if the repo was ever private.
