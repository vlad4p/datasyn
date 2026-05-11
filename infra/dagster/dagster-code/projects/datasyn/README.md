# datasyn

Datasyn code location.

Scaffolded by `dagster-mcp`. Layout:

```
datasyn/
├── pyproject.toml
├── workspace.yaml
├── Dockerfile
└── src/
    └── datasyn/
        ├── __init__.py
        ├── definitions.py
        ├── assets/
        │   ├── bronze/
        │   │   ├── indec_censo/
        │   │   └── indec_eph/
        │   ├── silver/
        │   └── gold/
        ├── jobs/
        ├── schedules/
        ├── sensors/
        └── utils/
```

## Build & run via the MCP

```text
dagster_deploy         project="datasyn" host_port=3001
```

`dagster_deploy` runs `docker build` from this directory, then replaces the
project container (same as `build_image` + force-recreate). Use
`dagster_build_image` alone if you only need an image. Set `container_port=4000`
when the Dockerfile runs `dagster api grpc` on 4000.

The container exposes the Dagster UI (or gRPC) on the chosen host port; the MCP attaches
the container to the `datacyber_mcp` Docker network so it can reach the other
Datacyber services (e.g. `duckdb-mcp:8040`, `storage-mcp:8044`).

## Local (without the MCP)

```bash
cd datasyn
pip install -e .
dagster dev -w workspace.yaml
```
