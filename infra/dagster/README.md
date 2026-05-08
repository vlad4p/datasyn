# MVP Dagster (docker compose)

Local Docker Compose deployment of [Dagster](https://dagster.io/), adapted from the upstream [`deploy_docker` example](https://github.com/dagster-io/dagster/tree/master/examples/deploy_docker), with a Python project (`ubika_dagster`) laid out per the official guide on [Projects and workspaces](https://docs.dagster.io/guides/build/projects).

Four long-running containers plus one container per Dagster run:

| Service                | Role                                                                                         |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| `dagster_postgresql`   | Postgres 16 used for run storage, schedule storage and event log storage.                    |
| `dagster_user_code`    | gRPC server that loads the `ubika_dagster` package. One per code location.                   |
| `dagster_webserver`    | `dagster-webserver` (UI + GraphQL). Submits runs to a queue via `QueuedRunCoordinator`.      |
| `dagster_daemon`       | `dagster-daemon run`: dequeues runs, evaluates schedules and sensors.                        |
| _per-run containers_   | Launched by `DockerRunLauncher` using the `dagster_user_code_image` image.                   |

The webserver and daemon mount `/var/run/docker.sock` so they can launch/stop per-run containers on the host Docker engine. `DAGSTER_CURRENT_IMAGE` (set on `dagster_user_code`) tells the launcher to reuse the same user-code image for runs.

## Project layout (`ubika_dagster`)

Following [Dagster's recommended project structure](https://docs.dagster.io/guides/build/projects):

```text
live/mvp/dagster/
├── pyproject.toml                   # PEP 621; declares the ubika-dagster package
├── README.md
├── Dockerfile_dagster               # webserver + daemon image
├── Dockerfile_user_code             # gRPC user-code image (pip installs the package)
├── docker-compose.yaml
├── dagster.yaml                     # instance config (storages, run launcher, scheduler)
├── workspace.yaml                   # gRPC code locations
├── Makefile                         # docker + python helpers
├── seed/
│   └── people.csv                   # sample input for csv_pipeline
├── src/
│   └── ubika_dagster/
│       ├── __init__.py
│       ├── definitions.py           # composition root (loaded by `dagster api grpc -m`)
│       └── defs/
│           ├── __init__.py          # one subpackage per project
│           └── csv_pipeline/
│               ├── __init__.py
│               ├── assets.py
│               ├── jobs.py
│               └── resources.py
└── tests/
    ├── __init__.py
    └── test_csv_pipeline.py
```

`pyproject.toml` declares `[tool.dagster] module_name = "ubika_dagster.definitions"`, so any local Dagster CLI usage and the gRPC server in `Dockerfile_user_code` (`dagster api grpc -m ubika_dagster.definitions`) load the same module. New projects are added by dropping a subpackage under `src/ubika_dagster/defs/` — `definitions.py` discovers their assets via [`load_assets_from_package_module`](https://docs.dagster.io/api/dagster/definitions#dagster.load_assets_from_package_module).

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
cd live/mvp/dagster
make seed-data    # copy seed/people.csv to /tmp/dagster_data/input/
make up           # build images and start all services
make logs         # tail logs (Ctrl-C to stop tailing)
open http://127.0.0.1:3001/   # Dagster UI
```

In the UI:

1. Open the **`ubika_dagster`** code location → **`csv_pipeline_job`**.
2. Click **Materialize all** (or **Launchpad** → **Launch run**).
3. Once green, inspect the result on the host:

```bash
make view-output
# or:
ls -la /tmp/dagster_data/output/
cat   /tmp/dagster_data/output/people_processed.csv
```

Stop it:

```bash
make down         # stop + remove containers, keep DB volume
make clean        # same, but also remove the Postgres volume (DESTRUCTIVE)
make clean-data   # remove /tmp/dagster_data on the host (DESTRUCTIVE)
```

## First project: `csv_pipeline`

Read a CSV from a local path, transform it, write a CSV to another local path.

```text
host: /tmp/dagster_data/input/people.csv
        │  (bind-mounted into every Dagster container as /opt/dagster/data/input)
        ▼
asset:  raw_people            (ubika_dagster.defs.csv_pipeline.assets)
        │  list[dict]
        ▼
asset:  processed_people      (ubika_dagster.defs.csv_pipeline.assets)
        │  uppercase `name`, add `name_length`
        ▼
host: /tmp/dagster_data/output/people_processed.csv
```

Components (under [`src/ubika_dagster/defs/csv_pipeline/`](src/ubika_dagster/defs/csv_pipeline/)):

- [`resources.py`](src/ubika_dagster/defs/csv_pipeline/resources.py) — `CsvPathsResource` (`ConfigurableResource`) with `input_dir`, `output_dir`, `input_filename`, `output_filename`. Defaults align with the bind mount (`/opt/dagster/data/{input,output}`); override via run config in the launchpad.
- [`assets.py`](src/ubika_dagster/defs/csv_pipeline/assets.py) — `raw_people` (reads CSV, fails fast with a helpful message if the file is missing) and `processed_people` (transforms + writes CSV). Both attach `path`, `num_rows`, `columns`, and a row preview as Dagster output metadata.
- [`jobs.py`](src/ubika_dagster/defs/csv_pipeline/jobs.py) — `csv_pipeline_job` selecting the `csv_pipeline` asset group, tagged `operation=example` so it goes through the queued run coordinator's tag concurrency limit.

[`src/ubika_dagster/definitions.py`](src/ubika_dagster/definitions.py) wires it all into a single `Definitions` and binds `paths -> CsvPathsResource()`.

### Why `/tmp/dagster_data`?

The `DockerRunLauncher` spawns a **brand new container** for every Dagster run, so the input CSV must be inside that container. `dagster.yaml`'s `run_launcher.container_kwargs.volumes` does not support env-var interpolation, so the host path has to be hard-coded. `/tmp/dagster_data` is a host path that is auto-shared on Docker Desktop (macOS / Windows) and trivially available on Linux. The same path is bind-mounted into `dagster_user_code`, `dagster_webserver` and `dagster_daemon` so in-process or `docker exec`-style runs work too.

To use a different host path, edit `volumes:` in:

- [`docker-compose.yaml`](docker-compose.yaml) — `dagster_user_code`, `dagster_webserver`, `dagster_daemon`.
- [`dagster.yaml`](dagster.yaml) — `run_launcher.container_kwargs.volumes`.

Or override the directories per run from the launchpad:

```yaml
resources:
  paths:
    config:
      input_dir: /opt/dagster/data/input
      output_dir: /opt/dagster/data/output
      input_filename: my_other_file.csv
      output_filename: my_output.csv
```

## Files

- [`pyproject.toml`](pyproject.toml) — package metadata, runtime + `dev` extras (pytest, ruff), `[tool.dagster] module_name`.
- [`docker-compose.yaml`](docker-compose.yaml) — services, `dagster_network`, volumes.
- [`Dockerfile_dagster`](Dockerfile_dagster) — image for webserver + daemon (no user code).
- [`Dockerfile_user_code`](Dockerfile_user_code) — image for the gRPC user-code server; `pip install`s `ubika-dagster` from `src/`. Reused for per-run containers via `DAGSTER_CURRENT_IMAGE`.
- [`dagster.yaml`](dagster.yaml) — `DagsterDaemonScheduler` + `QueuedRunCoordinator` + `DockerRunLauncher`, Postgres storages, shared data bind mount for run containers.
- [`workspace.yaml`](workspace.yaml) — loads the `ubika_dagster` code location from the `dagster_user_code` gRPC server.
- [`src/ubika_dagster/`](src/ubika_dagster/) — Dagster project package (`definitions.py` + `defs/<project>/`).
- [`tests/`](tests/) — pytest suite (`test_csv_pipeline.py` covers the assets, the job, and the `Definitions` import path).
- [`seed/people.csv`](seed/people.csv) — sample input copied into `/tmp/dagster_data/input/` by `make seed-data`.
- [`Makefile`](Makefile) — thin wrapper over `docker compose` plus `venv` / `install` / `test` / `lint` (`make help`).

## Local development (without Docker)

```bash
cd live/mvp/dagster
make install           # creates .venv and pip install -e '.[dev,webserver]'
make test              # pytest
make lint              # ruff check src tests
.venv/bin/dagster dev  # local Dagster UI on http://127.0.0.1:3000 using src/ubika_dagster
```

`dagster dev` uses `pyproject.toml`'s `[tool.dagster] module_name`, so it picks up the same code location as the gRPC server in Docker.

## Adding a new project

1. Create a subpackage under `src/ubika_dagster/defs/<new_project>/` with `__init__.py`, `assets.py`, etc.
2. If it ships a job, schedule, sensor or resource, import it from `src/ubika_dagster/definitions.py` and add it to `_collect_jobs()` / `_build_resources()`.
3. `make test` then `make up` to rebuild and reload.

## Adding a new code location

1. Add another user-code service in `docker-compose.yaml` (copy `dagster_user_code`, give it a new container name, image name and its own `Dockerfile_user_code_*`).
2. Append a `grpc_server` entry in [`workspace.yaml`](workspace.yaml) pointing at the new service's hostname/port and a unique `location_name`.
3. `make up` to rebuild and reload.

## Postgres access

```bash
make psql         # psql shell as postgres_user on postgres_db
```

Credentials are set in [`docker-compose.yaml`](docker-compose.yaml) (`postgres_user` / `postgres_password`). Change them there and in the `DAGSTER_POSTGRES_*` env vars before exposing this stack anywhere beyond a dev machine.

## Notes / limitations

- Python `3.11-slim` base image (upstream uses `3.10-slim`).
- Postgres `16-alpine` (upstream uses `postgres:11`) to match the rest of `live/mvp/`.
- The webserver/daemon require the host Docker socket; on SELinux or rootless-Docker hosts you may need to adjust the volume mount.
- No Terraform / EC2 deployment yet — this folder is just the Compose app. Follow [`../litellm/infra/`](../litellm/infra/) if/when you want to lift it onto an MVP EC2 instance.
