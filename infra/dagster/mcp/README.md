# dagster-mcp

FastMCP HTTP server (port `8043`, path `/mcp`) that scaffolds Dagster code-location
projects and drives the host Docker daemon to build images and run/replace
project containers. Register it in the repo root **`mcp.json`** under the key
**`dagster`** (LangChain prefixes tools as `dagster_*`).

This MCP follows the same idea as Dagster’s **AI-driven data engineering** story:
give agents **deterministic, bounded actions** (scaffold, add asset, compose
recreate) instead of free-form edits to production code locations, and pair that
with human verification. See [Announcing AI Driven Data Engineering](https://dagster.io/blog/announcing-ai-driven-data-engineering)
and [Accelerate Data Pipeline Development with Dagster Components](https://dagster.io/blog/accelerate-data-pipeline-development-with-dagster-components)
for the product direction (CLI `dg`, components, MCP-friendly structure).

## Layout

```
infra/dagster/mcp/
├── Dockerfile                # Python 3.12 + docker-ce-cli + compose plugin
├── requirements.txt          # fastmcp, python-dotenv, psycopg
├── server.py                 # FastMCP HTTP server (tools listed below)
├── scaffold.py               # pure-Python project / asset / job / schedule / sensor templating
├── docker_ops.py             # subprocess wrapper around the host Docker CLI
├── catalog_db.py             # optional PostgreSQL catalog connection
├── catalog_sql_guard.py      # SQL allowlist for catalog_execute_query
├── catalog_schema_inspect.py # public schema introspection
└── templates/                # `.tpl` files filled via `str.format`
```

Scaffolded and hand-maintained code locations live under **`../dagster-code/projects/`** (mounted as `/projects` in the `dagster-mcp` service — see **`../docker-compose.yaml`**).

The MCP **does not import Dagster**. It writes Python under `/projects/<name>/` and shells out to `docker` on the host (socket mount).

## Tools (LangChain prefix `dagster_`)

| Tool                       | Purpose |
|----------------------------|---------|
| `dagster_list_projects`    | List every scaffolded project under `DAGSTER_PROJECTS_ROOT`. |
| `dagster_create_project`   | Generate a new Dagster project (pyproject, Dockerfile, workspace, package, example asset+job). |
| `dagster_add_asset`        | File-per-asset (`<pkg>/assets/<name>.py`), auto-discovered. |
| `dagster_add_job`          | File-per-job using `define_asset_job`; `selection="*"` or comma-separated keys. |
| `dagster_add_schedule`     | `ScheduleDefinition` linked to an existing job (`cron` defaults to `0 9 * * *`). |
| `dagster_add_sensor`       | `@sensor` linked to an existing job (default body emits `SkipReason`). |
| `dagster_build_image`      | `docker build`; default tag `<prefix>/<project>:latest`, optional `image_name` (e.g. `dagster_user_code_image`). |
| `dagster_deploy`           | Default: `docker build` from the project dir, then replace `<prefix>-<project>` on `infra-datasynk`. Optional `image_name`; set `rebuild=false` to skip build and only recreate the container. |
| `dagster_stop` / `dagster_remove` | Lifecycle (`docker stop`, `docker rm -f`, optional image cleanup). |
| `dagster_logs`             | Tail container logs. |
| `dagster_status`           | List containers labeled `datacyber.dagster.project`. |
| `dagster_daemon_info`      | `docker info -f json` — confirms socket access. |
| `dagster_compose_force_recreate` | `docker compose … up -d --force-recreate` for mounted stack (e.g. refresh `dagster_user_code` after retagging an image). |
| `dagster_user_code_refresh` | Build default code-location project as `dagster_user_code_image`, then force-recreate `dagster_user_code` (needs `DAGSTER_COMPOSE_FILE` mounted). |
| `dagster_catalog_get_schema` | `public` tables, columns, FKs in the metadata catalog DB (optional). |
| `dagster_catalog_execute_query` | One guarded SQL statement per call against that DB (`DATABASE_URL` or `CATALOG_DATABASE_URL`). |

## HTTP health

`GET /health` returns `200` with body `ok` when the projects root exists (used for readiness checks).

## Generated project shape

```
projects/<name>/
├── pyproject.toml          # `[tool.dagster] module_name = <name>.definitions`
├── workspace.yaml          # `python_module: <name>.definitions`
├── Dockerfile              # `dagster dev -h 0.0.0.0 -p 3000 -w workspace.yaml`
├── .dockerignore
├── README.md
└── <name>/
    ├── __init__.py         # exports `defs`
    ├── definitions.py      # `Definitions(assets=..., jobs=..., schedules=..., sensors=...)`
    ├── _collect.py         # discovers `<pkg>.<sub>.<name>` symbols by module name
    ├── assets/             # `from . import <module>; @asset def <module>(): ...`
    ├── jobs/
    ├── schedules/
    └── sensors/
```

`definitions.py` calls `load_assets_from_package_module(assets)` for assets, and
for `jobs/schedules/sensors` uses `_collect.collect_named(<pkg>)` which imports
each submodule and picks the symbol whose name matches the file. So adding a
new file via `dagster_add_*` is automatically wired in — no central registry to
keep in sync.

## End-to-end example

```text
dagster_create_project   name="indec_pipeline" description="ETL for INDEC EPH"
dagster_add_asset        project="indec_pipeline" name="usu_hogar_raw" group="indec"
dagster_add_asset        project="indec_pipeline" name="usu_hogar_clean" group="indec"
dagster_add_job          project="indec_pipeline" name="indec_full" selection="*"
dagster_add_schedule     project="indec_pipeline" name="daily_indec" job="indec_full" cron="0 6 * * *"
dagster_build_image      project="indec_pipeline" image_name="dagster_user_code_image"
dagster_deploy           project="indec_pipeline" host_port=3001 container_port=4000 image_name="dagster_user_code_image"
# deploy defaults to build-then-replace; omit build_image if you only need one step.
# → code-location gRPC on host port 3001 (map `container_port` to match your Dockerfile CMD)
```

## Deployment expectations

The Dagster project containers join the `infra-datasynk` Docker network so
they can reach the rest of the stack by hostname (`duckdb-mcp:8040`,
`storage-mcp:8044`).

The Dagster UI ports start at `3001` to avoid colliding with `langfuse` on
`3000`. Pick a different `host_port=` per project.

## Environment

| Var                            | Default               | Notes |
|--------------------------------|-----------------------|-------|
| `HOST`                         | `0.0.0.0`             | FastMCP bind. |
| `PORT`                         | `8043`                | FastMCP HTTP port. |
| `MCP_HTTP_PATH`                | `/mcp`                | FastMCP HTTP path. |
| `DAGSTER_PROJECTS_ROOT`        | `/projects`           | Host-mounted volume containing scaffolded projects. |
| `DAGSTER_PROJECT_NETWORK`      | `infra-datasynk`      | Docker network the deployed containers join. |
| `DAGSTER_IMAGE_PREFIX`         | `dagster`             | Image name = `<prefix>/<project>:<tag>`. |
| `DAGSTER_CONTAINER_PREFIX`     | `dagster`             | Container name = `<prefix>-<project>`. |
| `DAGSTER_DEFAULT_HOST_PORT`    | `3001`                | Used when `dagster_deploy host_port=0`. |
| `DAGSTER_WEBSERVER_PORT`       | `3000`                | Port the Dagster UI binds inside the container. |
| `DAGSTER_DOCKER_TIMEOUT`       | `900`                 | Per-`docker` subprocess timeout (seconds). |
| `DAGSTER_COMPOSE_FILE`         | *(see compose)*       | Path to `docker-compose.yaml` inside the MCP container (Compose mounts `infra/dagster` at `/dagster-compose`). |
| `DAGSTER_COMPOSE_PROJECT`      | `dagster`             | `docker compose -p` project name (match the host). |
| `DAGSTER_COMPOSE_USER_CODE_SERVICE` | `dagster_user_code` | Default service for `compose_force_recreate` / `user_code_refresh`. |
| `DAGSTER_USER_CODE_BUILD_PROJECT` | `datasyn`         | Project directory under `DAGSTER_PROJECTS_ROOT` to build as the main code location image. |
| `DAGSTER_USER_CODE_IMAGE_NAME` | `dagster_user_code_image` | Image tag target for that build. |
| `DAGSTER_DEPLOY_VOLUMES`       | `duckdb_data:…;storage:…` | Semicolon-separated `src:dst` mounts for `dagster_deploy`. |
| `DATABASE_URL` / `CATALOG_DATABASE_URL` | *(empty)*   | PostgreSQL catalog for `dagster_catalog_*` tools. |
| `CATALOG_LIST_CAP`             | `100`                 | Max rows cap for catalog queries (clamped 1–500). |
