# MVP Dagster (docker compose)

Part of the Datacyber monorepo. For shared network, volumes, and `make` orchestration across stacks, see the repo root **`README.md`**.

Local Docker Compose deployment of [Dagster](https://dagster.io/), adapted from the upstream [`deploy_docker` example](https://github.com/dagster-io/dagster/tree/master/examples/deploy_docker). Production user code lives in sibling repo **`../datasyn-code`** (`datasyn` package at repo root). **dagster-mcp** lives in **`infra/dagster/mcp/`** (same repo). The **`ubika_dagster`** tree under this folder is a legacy reference layout.

Four long-running containers plus one container per Dagster run:

| Service                | Role                                                                                         |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| `dagster_postgresql`   | Postgres 16 used for run storage, schedule storage and event log storage.                    |
| `dagster_user_code`    | gRPC server that loads the **`datasyn`** package; image ref is `${DATASYN_IMAGE_REGISTRY}/${DATASYN_IMAGE_NAMESPACE}/dagster_user_code_image`, built from **`../datasyn-code`**. |
| `dagster_webserver`    | `dagster-webserver` (UI + GraphQL). Submits runs to a queue via `QueuedRunCoordinator`.      |
| `dagster_daemon`       | `dagster-daemon run`: dequeues runs, evaluates schedules and sensors.                        |
| `dagster-mcp`          | HTTP MCP server (`:8043/mcp`) — scaffold, build, catalog SQL; mounts **`../datasyn-code`** at `/code`. |
| _per-run containers_   | Launched by `DockerRunLauncher` using the same ref as **`DAGSTER_CURRENT_IMAGE`** on `dagster_user_code`.                   |

The webserver and daemon mount `/var/run/docker.sock` so they can launch/stop per-run containers on the host Docker engine. `DAGSTER_CURRENT_IMAGE` (set on `dagster_user_code`) tells the launcher to reuse the same code-location image for runs.

## Project layout

Following [Dagster's recommended project structure](https://docs.dagster.io/guides/build/projects):

```text
infra/dagster/
├── docker-compose.yaml              # postgres, gRPC code location, webserver, daemon, dagster-mcp
├── mcp/                             # dagster-mcp HTTP server (:8043)
│   ├── Dockerfile
│   ├── server.py
│   └── templates/
├── runtime/
│   ├── Dockerfile                   # webserver + daemon image
│   ├── dagster.yaml                 # instance config (storages, run launcher, scheduler)
│   └── workspace.yaml               # gRPC code locations
├── postgres/
│   └── Dockerfile                   # FROM postgres:16-alpine
└── Makefile

../datasyn-code/                     # sibling repo — active ``datasyn`` code location + gRPC Dockerfile
```

The deployed gRPC image is built from **`../datasyn-code`** (`datasyn.definitions`). Optional local **`pyproject.toml`** here declares `[tool.dagster] module_name = "ubika_dagster.definitions"` for the legacy layout only.

## Ports (host)

Deliberately chosen so the stack can run alongside `../langfuse` and `../litellm` on the same host:

| Stack    | Host ports                                                       |
| -------- | ---------------------------------------------------------------- |
| Langfuse | `3000`, `3030`, `5432`, `6379`, `8123`, `9000`, `9090`, `9091`   |
| LiteLLM  | `4000`, `127.0.0.1:5434`                                         |
| Dagster  | **`3001`** (webserver UI → container `3000`)                     |

Postgres for Dagster is **not** published on the host; the other containers reach it over the `dagster_network` bridge.

## Quick start

```bash
cd infra/dagster
make up           # build images and start all services
make logs         # tail logs (Ctrl-C to stop tailing)
open http://127.0.0.1:3001/   # Dagster UI
```

See [`mcp/README.md`](mcp/README.md) for dagster-mcp tools and [`../datasyn-code`](../../../datasyn-code) for production user code.

Stop the stack:

```bash
make down         # stop + remove containers, keep DB volume
make clean        # same, but also remove the Postgres volume (DESTRUCTIVE)
```

## Postgres access

```bash
make psql         # psql shell as postgres_user on postgres_db
```

Credentials are set in [`docker-compose.yaml`](docker-compose.yaml) (`postgres_user` / `postgres_password`).

## Notes / limitations

- The webserver/daemon require the host Docker socket; on SELinux or rootless-Docker hosts you may need to adjust the volume mount.
- Production pipelines live in sibling **`../datasyn-code`** — new ingests follow gitflow there (see root `README.md`).

