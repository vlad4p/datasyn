# Dagster user code (stub)

This folder is the **default gRPC code location** when sibling repo **`../datasyn-code`** is not present. It exports empty `Definitions()` so the Dagster control plane can start without production pipelines.

Production pipelines live in **[`datasyn-code`](https://github.com/YOUR_ORG/datasyn-code)**. Build and deploy from there, or:

```bash
make -C ../../infra dagster-user-code-build
make -C ../../infra up
```

Swap the running container after building a new image:

```bash
make -C ../../infra/dagster user-code-build
docker compose -f ../docker-compose.yaml up -d --force-recreate dagster_user_code
```

See [`../README.md`](../README.md) and root [`INSTALL.md`](../../../INSTALL.md).
