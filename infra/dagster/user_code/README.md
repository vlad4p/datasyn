# Empty Dagster user code (dev stub)

This image lets **`infra/dagster/docker-compose.yaml`** start a healthy gRPC code location
without checking out production pipelines in this repo.

| Image | Built from | Purpose |
| ----- | ---------- | ------- |
| `datasyn/dagster_user_code_image:latest` | **`user_code/`** (stub) | Empty `Definitions()` — used when `../datasyn-code` is missing |
| Same tag | Sibling repo **`../datasyn-code`** | Real `datasyn` assets, jobs, schedules (preferred) |

## Production image (sibling repo)

```bash
# From datasyn repo (builds ../datasyn-code when present):
make dagster-user-code-build
make infra-up

# Or from datasyn-code:
make build          # → datasyn/dagster_user_code_image:latest
make push           # remote registry only

# Recreate after code changes:
docker compose -f infra/dagster/docker-compose.yaml up -d --force-recreate dagster_user_code
```

Set **`DAGSTER_CURRENT_IMAGE`** on `dagster_user_code` to the same ref the daemon uses for
`DockerRunLauncher` per-run containers.
