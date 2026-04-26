# {name}

{description}

Scaffolded by `dagster-mcp`. Layout:

```
{name}/
├── pyproject.toml
├── workspace.yaml
├── Dockerfile
└── {name}/
    ├── __init__.py            # exports `defs` (the Dagster Definitions)
    ├── definitions.py         # auto-collects assets / jobs / schedules / sensors
    ├── _collect.py            # discovers symbols by submodule name
    ├── assets/                # one file per @asset (filename == symbol name)
    ├── jobs/                  # one file per job
    ├── schedules/             # one file per schedule
    └── sensors/               # one file per sensor
```

## Build & run via the MCP

```text
dagster_build_image    project="{name}"
dagster_deploy         project="{name}" host_port=3001
```

The container exposes the Dagster UI on the chosen host port; the MCP attaches
the container to the `datacyber_mcp` Docker network so it can reach the other
Datacyber services (e.g. `duckdb-mcp:8040`, `scrapper-mcp:8042`).

## Local (without the MCP)

```bash
cd {name}
pip install -e .
dagster dev -w workspace.yaml
```
