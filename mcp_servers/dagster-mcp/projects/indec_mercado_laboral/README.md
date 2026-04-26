# indec_mercado_laboral

INDEC Mercado Laboral pipelines (EPH and related open data).

Structure matches the Dagster basics tutorial — [Dagster project structure](https://docs.dagster.io/dagster-basics-tutorial/projects#dagster-project-structure):

```
.
├── pyproject.toml
├── README.md
├── src
│   └── indec_mercado_laboral
│       ├── __init__.py
│       ├── definitions.py
│       └── defs
│           └── __init__.py
├── tests
│   └── __init__.py
└── uv.lock
```

- **`pyproject.toml`** — project metadata and dependencies ([uv](https://docs.astral.sh/uv/) + `[dependency-groups]` dev includes `dagster-dg-cli`).
- **`src/indec_mercado_laboral/definitions.py`** — the `Definitions` object Dagster loads (`workspace.yaml` points here).
- **`src/indec_mercado_laboral/defs/`** — add modular definitions as the pipeline grows (tutorial convention).

## Run the UI (tutorial)

```bash
cd mcp_servers/dagster-mcp/projects/indec_mercado_laboral
uv sync
uv run dg dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

## EPH ingest assets (2025 + quarters)

Two **partitioned** assets scan **`{INDEC_EPH_BASE}/{INDEC_EPH_YEAR}/Q*`** (nested `usu_*.txt` allowed, e.g. `Q1/.../usu_hogar_T125.txt`):

| Asset | Source | DuckDB table |
|--------|--------|----------------|
| `indec_usu_hogar` | `usu_hogar_*.txt` | `gold.indec_usu_hogar` |
| `indec_usu_individual` | `usu_individual_*.txt` | `gold.indec_usu_individual` |

Partitions are **one per `Q1`…`Q4` folder** under the year; each run **DELETE**s that year/quarter slice then **INSERT**s (idempotent rematerialize). CSV options match INDEC microdata: `delim=';'`, `header=true`, `quote='"'`, `decimal_comma=true`.

| Environment variable | Default |
|------------------------|---------|
| `INDEC_EPH_BASE` | `/data-local/indec/mercado_laboral/EPH` |
| `INDEC_EPH_YEAR` | `2025` |
| `DUCKDB_PATH` | `/data/warehouse.duckdb` |

Mount **`data-local`** into the Dagster container (e.g. `DAGSTER_DEPLOY_VOLUMES` on `dagster-mcp`) so `/data-local/...` paths resolve.

## Docker (dagster-mcp)

`Dockerfile` + `workspace.yaml` support `dagster dev` in a container for MCP deploys (`dagster_build_image` / `dagster_deploy`).
