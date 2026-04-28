# dagster-mcp

FastMCP HTTP server (port `8043`, path `/mcp`) that scaffolds Dagster code-location
projects and drives the host Docker daemon to build images and run/replace
project containers.

## Layout

```
mcp_servers/dagster-mcp/
├── Dockerfile                # Python 3.12 + docker-ce-cli + compose plugin
├── requirements.txt          # fastmcp, python-dotenv
├── server.py                 # FastMCP HTTP server (tools listed below)
├── scaffold.py               # pure-Python project / asset / job / schedule / sensor templating
├── docker_ops.py             # subprocess wrapper around the host Docker CLI
├── templates/                # `.tpl` files filled via `str.format`
└── projects/                 # host-mounted volume, the place every scaffolded project lives
```

The MCP itself **does not import Dagster**. It only writes Python files to
`projects/<name>/` and shells out to `docker build` / `docker run` against the
host daemon (mounted via `/var/run/docker.sock`).

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
| `dagster_deploy`           | Default: `docker build` from the project dir, then replace `<prefix>-<project>` on `datacyber_mcp`. Optional `image_name`; set `rebuild=false` to skip build and only recreate the container. |
| `dagster_stop` / `dagster_remove` | Lifecycle (`docker stop`, `docker rm -f`, optional image cleanup). |
| `dagster_logs`             | Tail container logs. |
| `dagster_status`           | List containers labeled `datacyber.dagster.project`. |
| `dagster_daemon_info`      | `docker info -f json` — confirms socket access. |

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
# → user-code gRPC on host port 3001 (map `container_port` to match your Dockerfile CMD)
```

## Deployment expectations

The Dagster project containers join the `datacyber_mcp` Docker network so
they can reach the rest of the stack by hostname (`duckdb-mcp:8040`,
`scrapper-mcp:8042`).

The Dagster UI ports start at `3001` to avoid colliding with `langfuse` on
`3000`. Pick a different `host_port=` per project.

## Environment

| Var                            | Default               | Notes |
|--------------------------------|-----------------------|-------|
| `HOST`                         | `0.0.0.0`             | FastMCP bind. |
| `PORT`                         | `8043`                | FastMCP HTTP port. |
| `MCP_HTTP_PATH`                | `/mcp`                | FastMCP HTTP path. |
| `DAGSTER_PROJECTS_ROOT`        | `/projects`           | Host-mounted volume containing scaffolded projects. |
| `DAGSTER_PROJECT_NETWORK`      | `datacyber_mcp`       | Docker network the deployed containers join. |
| `DAGSTER_IMAGE_PREFIX`         | `dagster`             | Image name = `<prefix>/<project>:<tag>`. |
| `DAGSTER_CONTAINER_PREFIX`     | `dagster`             | Container name = `<prefix>-<project>`. |
| `DAGSTER_DEFAULT_HOST_PORT`    | `3001`                | Used when `dagster_deploy host_port=0`. |
| `DAGSTER_WEBSERVER_PORT`       | `3000`                | Port the Dagster UI binds inside the container. |
| `DAGSTER_DOCKER_TIMEOUT`       | `900`                 | Per-`docker` subprocess timeout (seconds). |
