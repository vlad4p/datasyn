# Empty Dagster user code (dev stub)

This image lets **`infra/dagster/docker-compose.yaml`** start a healthy gRPC code location
without checking out production pipelines in this repo.

| Image | Built from | Purpose |
| ----- | ---------- | ------- |
| `dagster_user_code_image` (default) | **`user_code/`** (here) | Empty `Definitions()` — UI and daemon wiring only |
| Production | Sibling repo **`../datasyn-code`** | Real `datasyn` assets, jobs, schedules |

## Production image (sibling repo)

```bash
# From datasyn-code (separate checkout beside this repo)
make build push   # or your org’s publish target

# Point compose at the published tag, then recreate user code:
cd infra/dagster
docker compose up -d --force-recreate dagster_user_code
```

Set **`DAGSTER_CURRENT_IMAGE`** on `dagster_user_code` to the same ref the daemon uses for
`DockerRunLauncher` per-run containers.
