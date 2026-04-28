# datasynk

INDEC Mercado Laboral pipelines (EPH and related open data).

Structure matches the canonical Dagster layout — [Projects and workspaces](https://docs.dagster.io/guides/build/projects#projects):

```
.
├── pyproject.toml
├── README.md
├── Dockerfile
├── workspace.yaml
├── uv.lock
├── tests/
│   └── __init__.py
└── src/
    └── datasynk/
        ├── __init__.py
        ├── definitions.py
        └── defs/
            ├── __init__.py
            ├── _eph_year_discovery.py
            ├── assets/
            │   ├── __init__.py
            │   ├── bronze/
            │   │   ├── __init__.py
            │   │   ├── eph_year_usu.py
            │   │   └── variables_eph.py
            │   ├── silver/
            │   │   ├── __init__.py
            │   │   └── silver_variables.py
            │   └── gold/
            │       └── __init__.py
            ├── resources/
            │   ├── __init__.py
            │   └── database.py
            └── jobs/
                ├── __init__.py
                └── indec_mercado_laboral_variables_job.py
```

- **`pyproject.toml`** — project metadata and dependencies. Code-location entry point is `[tool.dagster].module_name = "datasynk.definitions"`.
- **`src/datasynk/definitions.py`** — composes assets/jobs/resources into one `Definitions` object.
- **`src/datasynk/defs/assets/`** — medallion hierarchy (`bronze`, `silver`, `gold`) with loader `__init__.py` modules.
- **`src/datasynk/defs/resources/database.py`** — shared `DuckDBResource` used by assets.
- **`src/datasynk/defs/jobs/`** — `define_asset_job` selections (e.g. `indec_mercado_laboral_variables_job` chains bronze → silver for the variable register).

## Run the UI (tutorial)

```bash
cd mcp_servers/dagster-mcp/projects/datasynk
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

## EPH variables PDF → LiteLLM vision → DuckDB (`variables_eph`)

| Asset | Source | DuckDB table |
|--------|--------|----------------|
| `variables_eph` | `INDEC_EPH_VARIABLES_PDF` (default: `…/EPH_registro_3T2025.pdf`) | `bronze.indec_mercado_laboral_variables` |

Pages **5–35** (1-based) are rasterized and sent to **LiteLLM** as OpenAI-style vision chat (`local/gemini-3.1-pro-preview` by default). Each row stores one page: `page_number`, `variables` (JSON array of objects), `source_pdf`, `model_id`, `extracted_at`. Rematerialize **DELETE**s prior rows for the same `source_pdf` then **INSERT**s.

| Environment variable | Default / notes |
|------------------------|------------------|
| `LITELLM_KEY` / `LITELLM_PROXY_KEY` | **Required** in user-code container for Bearer auth. |
| `LITELLM_API_BASE` / `LITELLM_PROXY_BASE` / `LITELLM_URL` | LiteLLM OpenAI root; `/v1` added if missing. In Docker, defaults rewrite toward `host.docker.internal:4000`. |
| `LITELLM_VARIABLES_MODEL` | `local/gemini-3.1-pro-preview` (must match LiteLLM `GET /v1/models`). |
| `INDEC_EPH_VARIABLES_PDF` | Optional absolute path. If unset, first ``eph_variables_pdf_path()``: ``{INDEC_EPH_BASE}`` is ``…/indec/mercado_laboral/EPH`` → PDF at ``…/indec/pdf-variables/…`` (sibling of ``mercado_laboral``, same ``INDEC_EPH_BASE`` as ``usu_*``). Then ``$DATA_LOCAL_ROOT/…``, ``/data-local/…``, ``dirname($DUCKDB_PATH)/data-local/…``. |
| `DATA_LOCAL_ROOT` | Optional extra search root (DuckDB MCP often uses ``/data-local``). |
| `INDEC_EPH_VARIABLES_PAGE_START` / `…_PAGE_END` | `5` / `35` |
| `INDEC_EPH_VARIABLES_PAGE_DELAY` | `1` — seconds to **sleep after each page** (after LiteLLM + DuckDB insert) to avoid saturating the proxy; set `0` to disable. |
| `INDEC_EPH_VARIABLES_LOG` | Optional absolute path for the processed-page log. Default order: (1) **`{pdf_dir}/log_processed_file.txt`** when that directory is writable (e.g. host dev runs); (2) otherwise **`{dirname(DUCKDB_PATH)}/dagster_logs/indec_mercado_laboral/{pdf.stem}.processed.log`** — the documented Docker default, since `/data-local` is typically mounted **read-only** while `/data` (the DuckDB volume) is RW. Each processed page appends one tab-separated line; run start/end write `# …` comment lines. |
| `LITELLM_VARIABLES_HTTP_TIMEOUT` | `180` (seconds per page request) |

## Docker (dagster-mcp)

`Dockerfile` + `workspace.yaml` support `dagster dev` in a container for MCP deploys (`dagster_deploy` builds and replaces the container by default; use `dagster_build_image` alone if you only need an image).
