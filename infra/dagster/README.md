# MVP Dagster (docker compose)

Part of the Datasyn monorepo. For shared network, volumes, and `make` orchestration across stacks, see the repo root **`README.md`**.

Local Docker Compose deployment of [Dagster](https://dagster.io/), adapted from the upstream [`deploy_docker` example](https://github.com/dagster-io/dagster/tree/master/examples/deploy_docker). The default **gRPC code location** is an **empty stub** in **`user_code/`** so this repo can run the control plane without production pipelines. Production user code lives in sibling repo **`../datasyn-code`** (or [`datasyn-code` on GitHub](https://github.com/YOUR_ORG/datasyn-code)). Legacy **`ubika_dagster`** metadata in **`pyproject.toml`** is unused when running the stub.

Four long-running containers plus one container per Dagster run:

| Service                | Role                                                                                         |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| `dagster_postgresql`   | Postgres 16 used for run storage, schedule storage and event log storage.                    |
| `dagster_user_code`    | gRPC server; default image from **`user_code/`** (empty `Definitions`). Swap tag for **`../datasyn-code`** when running real pipelines. |
| `dagster_webserver`    | `dagster-webserver` (UI + GraphQL). Submits runs to a queue via `QueuedRunCoordinator`.      |
| `dagster_daemon`       | `dagster-daemon run`: dequeues runs, evaluates schedules and sensors.                        |
| _per-run containers_   | Launched by `DockerRunLauncher` using the same ref as **`DAGSTER_CURRENT_IMAGE`** on `dagster_user_code`.                   |

The webserver and daemon mount `/var/run/docker.sock` so they can launch/stop per-run containers on the host Docker engine. `DAGSTER_CURRENT_IMAGE` (set on `dagster_user_code`) tells the launcher to reuse the same code-location image for runs.

## Project layout

Following [Dagster's recommended project structure](https://docs.dagster.io/guides/build/projects):

```text
infra/dagster/
├── docker-compose.yaml              # postgres, gRPC code location, webserver, daemon
├── user_code/                       # empty dev stub (default dagster_user_code image)
│   ├── Dockerfile
│   └── definitions.py
├── runtime/
│   ├── Dockerfile                   # webserver + daemon image
│   ├── dagster.yaml                 # instance config (storages, run launcher, scheduler)
│   └── workspace.yaml               # gRPC code locations
├── postgres/
│   └── Dockerfile                   # FROM postgres:16-alpine
└── Makefile

../datasyn-code/                     # sibling repo — production ``datasyn`` code location
```

The deployed gRPC image defaults to **`user_code/`**. For production, build from **`../datasyn-code`** and recreate `dagster_user_code` (see [`user_code/README.md`](user_code/README.md)). Optional local **`pyproject.toml`** here declares `[tool.dagster] module_name = "ubika_dagster.definitions"` for the legacy layout only.

## Ports (host)

Deliberately chosen so the stack can run alongside `../langfuse` and `../litellm` on the same host:

| Stack    | Host ports                                                       |
| -------- | ---------------------------------------------------------------- |
| Langfuse | `3000`, `3030`, `5432`, `6379`, `8123`, `9000`, `9090`, `9091`   |
| LiteLLM  | `4000`, `127.0.0.1:5434`                                         |
| Dagster  | **`3001`** (webserver UI → container `3000`)                     |

Postgres for Dagster is **not** published on the host; the other containers reach it over the `infra-datasynk` bridge.

## Quick start

```bash
cd infra/dagster
make up           # build images and start all services
make logs         # tail logs (Ctrl-C to stop tailing)
open http://127.0.0.1:3001/   # Dagster UI
```

See [`user_code/README.md`](user_code/README.md) for swapping in the production image and [`../datasyn-code`](../../../datasyn-code) for pipeline development.

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

- **Warehouse (Quack):** Dagster does not mount `warehouse.duckdb`. Set **`QUACK_URI`**, **`QUACK_TOKEN`**, and **`QUACK_DISABLE_SSL`** in `.env` (see `.env.example`) to point at VM1 `duckdb-mcp` (`:9494`). Per-run containers receive the same vars via `DockerRunLauncher.env_vars` in `runtime/dagster.yaml`.
- **MinIO reads:** Bronze CSV assets use `read_csv_auto('s3://bucket/key')` with an httpfs S3 secret (`MINIO_*` env) — data stays in object storage until materialized into `bronze.*` on the remote warehouse.
- **Per-run containers** mount `/data-local` from the host path in `DATASYN_DATA_LOCAL_HOST` (see `.env.example`). The runtime **entrypoint** renders `dagster.yaml` from the template at container start (DockerRunLauncher volumes cannot use compose env vars). `make patch-runtime` still writes `runtime/dagster.local.yaml` for inspection.

### Troubleshooting: `__DATASYN_DATA_LOCAL_HOST__` invalid volume name

`DockerRunLauncher` read a config where the `__DATASYN_DATA_LOCAL_HOST__` placeholder was not substituted. Common causes:

1. **`DATASYN_DATA_LOCAL_HOST` unset** in `infra/dagster/.env` on the VM — set an **absolute** host path (fleet: `provision-vm.sh` writes `${REPO_DIR}/data-local`).
2. **`runtime/dagster.local.yaml` missing** (gitignored) and an older runtime image without the entrypoint — run `make patch-runtime` then recreate webserver/daemon, or deploy a build that includes `runtime/docker-entrypoint.sh`.
3. **Host path is a directory** because compose created `dagster.local.yaml` when the file was absent — `rm -rf runtime/dagster.local.yaml`, run `make patch-runtime`, recreate containers.

**Fleet VM (10.13.10.122) quick fix:**

```bash
cd ~/datasyn   # or your clone path
grep DATASYN_DATA_LOCAL_HOST infra/dagster/.env   # must be absolute, e.g. /home/.../datasyn/data-local
bash infra/dagster/scripts/patch-dagster-yaml.sh
ENVIRONMENT=prod make -C infra/dagster up   # rebuilds runtime if needed; entrypoint renders config at start
```
- The webserver/daemon require the host Docker socket; on SELinux or rootless-Docker hosts you may need to adjust the volume mount.
- Production pipelines live in sibling **`../datasyn-code`** — new ingests follow gitflow there (see root `README.md`).
