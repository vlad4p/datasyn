# Datasyn — Infrastructure Requirements Specification

**Version:** 1.0  
**Status:** Draft for distributed deployment planning  
**Audience:** Platform / DevOps / solution architects  

This document defines **VM sizing**, **storage**, **networking**, and **docker-compose** placement for Datasyn when each **logical service runs on its own VM** (few concurrent users). It aligns with the existing repo layout under `infra/` and root `docker-compose.yaml`.

---

## 1. Scope and principles


| Principle                     | Description                                                                                                                                                                                                                                                                |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Compose-only**              | Every deployable unit is started with `docker compose` (no Kubernetes requirement in this spec).                                                                                                                                                                           |
| **One service domain per VM** | Each VM hosts **one** stack from the table below (that stack may include tightly coupled sidecars, e.g. `duckdb` + `duckdb-mcp`).                                                                                                                                          |
| **Shared overlay network**    | All VMs join the same logical Docker network **`infra-datasynk`** (create once: `make -C infra/object-storage bootstrap` or `docker network create infra-datasynk`). |
| **Named volumes**             | `duckdb_data` and `storage` are **external** volumes; create on the VM that owns the data plane before `up`.                                                                                                                                                               |
| **Few users**                 | Sizing assumes **1–10** concurrent analysts/agents, not multi-tenant SaaS scale.                                                                                                                                                                                           |
| **Data tiers**                | Three scenarios: **small**, **medium**, **high** (§4)—primarily **landing + warehouse + object storage** growth.                                                                                                                                                           |


**Out of scope for this doc:** cloud-specific Terraform modules, exact $/month pricing, and HA/failover (can be added as a follow-up).

---

## 2. Service catalog and compose mapping


| Logical service             | Role                                                            | Compose file                                         | Primary containers                                                               | Host ports (typical)         |
| --------------------------- | --------------------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------- | ---------------------------- |
| **Object storage (MinIO)**  | Landing zone, Parquet/Iceberg files, `data-local` bucket mirror | `infra/object-storage/docker-compose.yaml`           | `minio`, `storage-mcp`                                                           | MCP `8044` (optional expose) |
| **DuckDB analytics**        | OLAP warehouse (`warehouse.duckdb`), medallion schemas          | `infra/duckdb/docker-compose.yaml`                   | `duckdb`, `duckdb-mcp`, optional `duckdb-ui` (`--profile ui`)                    | MCP `8040`, UI `4213`        |
| **Dagster**                 | Orchestration: schedules, sensors, asset materializations       | `infra/dagster/docker-compose.yaml`                  | `dagster_postgresql`, `dagster_user_code`, `dagster_webserver`, `dagster_daemon` | UI `3001` → container `3000` |
| **LiteLLM**                 | Unified LLM proxy (OpenAI, DeepSeek, Qwen, local models, etc.)  | `infra/litellm/docker-compose.yaml`                  | `db` (Postgres), `litellm`                                                       | Proxy `4000`                 |
| **Langfuse**                | LLM/agent tracing (optional but recommended in prod)            | `infra/langfuse/docker-compose.yml` (upstream stack) | Langfuse app, worker, Postgres, Redis, ClickHouse, internal MinIO                | UI `3000`                    |
| **Datasyn agent (brain)**   | FastAPI + LangChain / Deep Agents, MCP clients                  | `docker-compose.yaml`                                | `brain`                                                                          | `8002`                       |
| **Datasyn UI**              | React (Vite build served in container)                          | `docker-compose.yaml`                                | `ui`                                                                             | `8003`                       |
| **OCI registry (optional)** | Image distribution for `ENVIRONMENT=prod`                       | `infra/distribution/docker-compose.yaml`             | Registry                                                                         | `5000`                       |


**MCP and Dagster user code** live in sibling repo `**datasyn-code`** (gRPC image `dagster_user_code_image`). Pipelines are **not** in this repo.

**DNS alias (critical):** Application MinIO must be reached as `**datasyn-object-minio:9000`** on `infra-datasynk`, not bare `minio` (Langfuse also registers `minio`).

---

## 3. Data stores and storage layout

### 3.1 Storage matrix


| Store                             | Technology                            | Owner VM / stack                               | Volume / path                                          | Contents                                                   |
| --------------------------------- | ------------------------------------- | ---------------------------------------------- | ------------------------------------------------------ | ---------------------------------------------------------- |
| **Landing (files)**               | Host dir + MinIO                      | Object storage VM + bind on DuckDB/Dagster VMs | Repo/host: `data-local/`; bucket `data-local` in MinIO | Raw CSV/TXT/HTML, scrape outputs, PDFs                     |
| **Object storage**                | MinIO (S3 API)                        | Object storage VM                              | Docker volume `storage` → `/data`                      | Parquet, Iceberg metadata/data, large binaries, Dagster IO |
| **Warehouse**                     | DuckDB file DB                        | DuckDB VM                                      | `duckdb_data` → `/data/warehouse.duckdb`               | `bronze` / `silver` / `gold` tables, views                 |
| **Dagster metadata**              | PostgreSQL 16                         | Dagster VM                                     | `dagster-db-data`                                      | Runs, events, schedules, sensors                           |
| **LiteLLM metadata**              | PostgreSQL 16                         | LiteLLM VM                                     | `litellm-db-data`                                      | Keys, spend logs, model registry                           |
| **Langfuse telemetry**            | Postgres + ClickHouse + Redis + MinIO | Langfuse VM                                    | Stack-defined volumes                                  | Traces, scores, sessions                                   |
| **Catalog (optional)**            | PostgreSQL                            | Dagster VM or dedicated small VM               | `DATABASE_URL` / `CATALOG_DATABASE_URL` on dagster-mcp | Dataset entities FTS (`dagster_catalog_*`)                 |
| **Agent ephemeral**               | Container FS                          | Brain VM                                       | `./reports`, `./skills` mounts                         | Markdown reports, read-only skills                         |
| **Dagster run scratch**           | Host `/tmp`                           | Dagster VM                                     | `/tmp/dagster_data`, `/tmp/io_manager_storage`         | Per-run Docker launcher IO                                 |
| **Iceberg / DuckLake (optional)** | MinIO + Iceberg REST                  | Object storage + config on Dagster             | `ICEBERG_REST_*` in `infra/dagster/.env`               | Table format on object storage; DuckDB attaches via REST   |


### 3.2 Medallion and formats


| Layer          | Schema (default) | Typical format                                         | Written by                   |
| -------------- | ---------------- | ------------------------------------------------------ | ---------------------------- |
| **Bronze**     | `bronze`         | Tables from `read_csv_auto`, scrape HTML→bronze tables | Dagster assets, agent ingest |
| **Silver**     | `silver`         | Cleaned / enriched tables                              | Dagster transforms           |
| **Gold**       | `gold`           | Marts (e.g. INDEC EPH `gold.indec_eph_*`)              | Dagster + agent SQL          |
| **Lake files** | Buckets/prefixes | **Parquet**, **Iceberg** (when REST configured)        | Dagster jobs, export assets  |


**Concurrency rule:** `warehouse.duckdb` allows **one writer** at a time. Dagster `max_concurrent_runs: 1` and pool limits in `infra/dagster/runtime/dagster.yaml` enforce this. Do not run `duckdb-ui` profile alongside heavy MCP ingest on the same file.

---

## 4. Sizing scenarios (few users)

Assumptions: **1–10** users, batch-heavy workloads, agent chat with moderate token volume. Adjust **up** if you run many parallel Dagster runs (after moving off file-backed DuckDB) or host **large local LLMs** on the LiteLLM VM.

### 4.1 Summary table


| VM role                      | Small data                           | Medium data                           | High data                                         |
| ---------------------------- | ------------------------------------ | ------------------------------------- | ------------------------------------------------- |
| **MinIO + storage-mcp**      | 2 vCPU, 4 GB RAM, **100 GB** SSD     | 4 vCPU, 8 GB RAM, **500 GB** SSD      | 8 vCPU, 16 GB RAM, **2–10 TB** SSD/NVMe           |
| **DuckDB + duckdb-mcp**      | 4 vCPU, **16 GB** RAM, **50 GB** SSD | 8 vCPU, **32 GB** RAM, **200 GB** SSD | 16 vCPU, **64–128 GB** RAM, **1 TB** NVMe         |
| **Dagster** (incl. Postgres) | 4 vCPU, 16 GB RAM, **100 GB** SSD    | 8 vCPU, 32 GB RAM, **300 GB** SSD     | 16 vCPU, 64 GB RAM, **1 TB** SSD                  |
| **LiteLLM** (+ Postgres)     | 2 vCPU, 4 GB RAM, 20 GB              | 4 vCPU, 8 GB RAM, 50 GB               | 8 vCPU, 16 GB RAM, 100 GB (+ GPU VM if local LLM) |
| **Langfuse**                 | 4 vCPU, 8 GB RAM, **100 GB**         | 4 vCPU, 16 GB RAM, **300 GB**         | 8 vCPU, 32 GB RAM, **1 TB**                       |
| **Brain**                    | 2 vCPU, 4 GB RAM, 20 GB              | 4 vCPU, 8 GB RAM, 50 GB               | 4 vCPU, 16 GB RAM, 100 GB                         |
| **UI**                       | 1 vCPU, 1 GB RAM, 10 GB              | 2 vCPU, 2 GB RAM, 20 GB               | 2 vCPU, 4 GB RAM, 20 GB                           |
| **GPU training (optional)**  | —                                    | 1× GPU 16 GB VRAM, 8 vCPU, 32 GB      | 1–2× GPU 24–48 GB VRAM, 16 vCPU, 64 GB            |


### 4.2 Data volume definitions


| Tier       | Landing (`data-local` + MinIO) | `warehouse.duckdb` | Typical sources                                                                  |
| ---------- | ------------------------------ | ------------------ | -------------------------------------------------------------------------------- |
| **Small**  | < **20 GB**                    | < **10 GB**        | Few CSV/TXT quarters, single news vertical, PoC catalogs                         |
| **Medium** | **20 GB – 500 GB**             | **10 – 100 GB**    | Multi-year EPH, several scrape targets, regular Parquet exports                  |
| **High**   | **500 GB – 5 TB+**             | **100 GB – 1 TB+** | Full INDEC history, many media scrapes, Iceberg tables, retained Langfuse traces |


### 4.3 Per-container resource hints (from repo defaults)

Use as **docker compose `deploy.resources`** overrides per scenario.


| Container                                | Small (limits) | Medium       | High                                             |
| ---------------------------------------- | -------------- | ------------ | ------------------------------------------------ |
| `dagster_user_code`                      | 2 CPU, 4 GB    | 2 CPU, 8 GB  | 4 CPU, 16 GB                                     |
| `dagster_daemon`                         | 1 CPU, 2 GB    | 2 CPU, 4 GB  | 4 CPU, 8 GB                                      |
| `dagster_webserver`                      | 1 CPU, 1 GB    | 1 CPU, 2 GB  | 2 CPU, 4 GB                                      |
| Dagster **per-run** job (`dagster.yaml`) | 2 CPU, 4 GB    | 4 CPU, 8 GB  | 4–8 CPU, 16–32 GB                                |
| `duckdb` / `duckdb-mcp`                  | 2 CPU, 8 GB    | 4 CPU, 24 GB | 8–16 CPU, 64–128 GB                              |
| `minio`                                  | 1 CPU, 2 GB    | 2 CPU, 4 GB  | 4 CPU, 8 GB                                      |
| `litellm`                                | 1 CPU, 2 GB    | 2 CPU, 4 GB  | 4 CPU, 8 GB (+ GPU host if serving local models) |
| `brain`                                  | 1 CPU, 2 GB    | 2 CPU, 4 GB  | 2 CPU, 8 GB                                      |


---

## 5. Distributed VM topology


| #   | VM name                   | Compose                                      | Bootstrap on VM                                                             |
| --- | ------------------------- | -------------------------------------------- | --------------------------------------------------------------------------- |
| 1   | `datasyn-minio`           | `infra/object-storage/docker-compose.yaml`   | `docker volume create storage`                                              |
| 2   | `datasyn-duckdb`          | `infra/duckdb/docker-compose.yaml`           | `docker volume create duckdb_data`; mount NFS/synced `data-local` if shared |
| 3   | `datasyn-dagster`         | `infra/dagster/docker-compose.yaml`          | `duckdb_data` + `storage` external; Docker socket for `DockerRunLauncher`   |
| 4   | `datasyn-litellm`         | `infra/litellm/docker-compose.yaml`          | Edit `config/config.yaml` model list                                        |
| 5   | `datasyn-langfuse`        | `infra/langfuse/docker-compose.yml`          | `make -C infra/langfuse init-env && make up`                                |
| 6   | `datasyn-brain`           | `docker-compose.yaml` (service `brain` only) | Clone repo; mount `skills/`, `reports/`                                     |
| 7   | `datasyn-ui`              | `docker-compose.yaml` (service `ui` only)    | `VITE_PROXY_TARGET=http://<brain-host>:8000`                                |
| 8   | `datasyn-registry` (prod) | `infra/distribution/docker-compose.yaml`     | `ENVIRONMENT=prod` image pull                                               |
| 9   | `datasyn-gpu` (optional)  | Custom compose or bare metal                 | CUDA drivers; invoked by Dagster ops                                        |


**Splitting root compose:** For strict one-service-per-VM, use `docker compose up brain` and `docker compose up ui` on separate hosts with the same `infra-datasynk` attachment.

### 5.2 Cross-VM connectivity checklist


| From         | To              | Variable / endpoint                                                                                 |
| ------------ | --------------- | --------------------------------------------------------------------------------------------------- |
| Brain        | LiteLLM         | `LITELLM_PROXY_BASE=http://<litellm-host>:4000`                                                     |
| Brain        | Langfuse        | `LANGFUSE_BASE_URL=http://<langfuse-host>:3000`                                                     |
| Brain        | MCP             | `mcp.json` URLs → `http://<duckdb-host>:8040/mcp`, `http://<minio-host>:8044/mcp`                   |
| Brain        | Dagster GraphQL | `DAGSTER_URL=http://<dagster-host>:3001` (host) or `http://dagster_webserver:3000` (same network)   |
| Dagster runs | MinIO           | `MINIO_ENDPOINT=http://datasyn-object-minio:9000`                                                   |
| Dagster runs | DuckDB file     | Shared volume **or** replicate `warehouse.duckdb` (not recommended)—prefer **one DuckDB writer VM** |
| LiteLLM      | Langfuse OTEL   | `LANGFUSE_OTEL_HOST` in `infra/litellm/.env`                                                        |
| UI           | Brain           | `VITE_PROXY_TARGET=http://<brain-host>:8000`                                                        |


### 5.3 Shared `data-local` across VMs


| Pattern                      | When                                                 | How                                                                           |
| ---------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------- |
| **NFS / cloud file share**   | Dagster and DuckDB on different hosts but same files | Mount same path; set `DATASYN_DATA_LOCAL_HOST` in `infra/dagster/.env`        |
| **MinIO as source of truth** | High data, many scrapers                             | Land via `storage_`* / Dagster → sync to DuckDB with `read_parquet` / exports |
| **Single DuckDB VM**         | Simplest                                             | Only `duckdb-mcp` and Dagster mount `duckdb_data`; no file replication        |


---

## 6. LiteLLM — multi-model hosting

Configure models in `infra/litellm/config/config.yaml` (see [LiteLLM proxy configs](https://docs.litellm.ai/docs/proxy/configs)).

**Example model entries (API keys in `.env`, not in YAML):**

```yaml
model_list:
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY

  - model_name: deepseek-chat
    litellm_params:
      model: deepseek/deepseek-chat
      api_key: os.environ/DEEPSEEK_API_KEY

  - model_name: qwen-plus
    litellm_params:
      model: openrouter/qwen/qwen-plus   # or dashscope direct
      api_key: os.environ/OPENROUTER_API_KEY

  # Local OpenAI-compatible server on GPU VM:
  - model_name: local-qwen-7b
    litellm_params:
      model: openai/qwen2.5-7b-instruct
      api_base: http://<gpu-host>:8080/v1
      api_key: os.environ/LOCAL_LLM_KEY
```

**Brain / Dagster:** set `MODEL_PROVIDER=litellm`, `CHAT_MODEL=<model_name>`, `LITELLM_KEY=<master-key>`.

**Observability:** keep `litellm_settings.callbacks: ["langfuse_otel"]` when Langfuse VM is up.

---

## 7. Use cases (architecture mapping)

### 7.1 Structure heterogeneous data for agents

**Goal:** Normalize files, tables, and catalog metadata so the **brain** can answer via MCP with minimal hallucination.


| Step                 | Component                                                                           |
| -------------------- | ----------------------------------------------------------------------------------- |
| Land files           | **MinIO** (`data-local` bucket) + host `data-local/`                                |
| Register / describe  | **Catalog Postgres** (`dagster_catalog_`*) + skills `catalog-sql`, `update-catalog` |
| Query & profile      | **duckdb-mcp** (`duckdb_get_schema`, `duckdb_execute_query`)                        |
| Orchestrate loads    | **Dagster** assets in `datasyn-code` (bronze → silver → gold)                       |
| Agent reasoning      | **brain** → `task` subagent `query` + skills under `/skills/`                       |
| Trace tool/LLM calls | **Langfuse**                                                                        |


**VMs involved:** minio, duckdb, dagster, brain, litellm, langfuse (optional).

---

### 7.2 Fine-tune small models with GPU (Dagster-orchestrated)

**Goal:** Periodic training jobs (LoRA/full fine-tune) on curated datasets exported from the warehouse.


| Step               | Component                                                                |
| ------------------ | ------------------------------------------------------------------------ |
| Build training set | Dagster asset: SQL in **DuckDB** → Parquet on **MinIO**                  |
| Schedule           | Dagster **schedule** / **sensor** on `datasyn-gpu` queue                 |
| Execute training   | **GPU VM** — container with CUDA, Hugging Face / MLX / custom script     |
| Register artifact  | Push adapter weights to **MinIO**; log run in **Dagster** + **Langfuse** |
| Serve inference    | **LiteLLM** `api_base` pointing to vLLM/TGI on GPU VM                    |


**Sizing:** see GPU row in §4.1; Dagster per-run limits ≥ dataset size in RAM.

**Note:** GPU training is **not** a built-in compose service today—add a `datasyn-code` job that `docker run`s the training image on the GPU host (same pattern as `DockerRunLauncher`).

---

### 7.3 Scrape multiple sources → structured DuckDB tables

**Goal:** Ingest news, INDEC EPH, PDFs, etc. into medallion tables.


| Step              | Component                                                                                       |
| ----------------- | ----------------------------------------------------------------------------------------------- |
| Scrape / download | Dagster ops or agent-driven flows; HTML/ZIP to **MinIO** / `data-local`                         |
| Bronze tables     | `read_csv_auto` / custom parsers via **duckdb_execute_query** (agent) or Dagster assets         |
| Skills            | e.g. `ingest-scrape-news-bronze`, `scrape-indec-mercado-laboral`, `ingest-indec-mercadolaboral` |
| Orchestration     | **Dagster** jobs (schedules per source)                                                         |
| Validation        | Row counts, `COUNT(*)`, schema checks in **gold** / **bronze**                                  |


**VMs involved:** minio, duckdb, dagster (heavy disk on minio + duckdb VMs).

---

### 7.4 Dagster as orchestration hub

**Responsibilities:**

- Materialize assets (scrapers, dbt-style SQL, exports).
- Enforce **single-writer** on `warehouse.duckdb`.
- Launch **DockerRunLauncher** children with env forwarded to MinIO, LiteLLM, Iceberg REST.

**Deploy:** single `datasyn-dagster` VM; ensure `/var/run/docker.sock` mounted (as in repo compose).

---

### 7.5 LiteLLM as LLM gateway

**Responsibilities:**

- Route chat completions to **DeepSeek**, **Qwen**, OpenAI, Anthropic, or **local** endpoints.
- Centralize API keys and model aliases for **brain** and **Dagster** LLM steps.
- Emit OTEL traces to **Langfuse**.

**Deploy:** dedicated `datasyn-litellm` VM; lock Postgres to localhost or private SG.

---

## 8. Deployment procedure (per VM)

### 8.1 Common bootstrap (once per environment)

```bash
# On a bastion or each VM (network plugin dependent):
docker network create infra-datasynk || true
docker volume create storage || true
docker volume create duckdb_data || true
```

### 8.2 Start order


| Order | Stack          | Command                                                                                 |
| ----- | -------------- | --------------------------------------------------------------------------------------- |
| 1     | Object storage | `make -C infra/object-storage up` or `ENVIRONMENT=prod make -C infra/object-storage up` |
| 2     | DuckDB         | `make -C infra/duckdb up`                                                               |
| 3     | Dagster        | `make -C infra/dagster up` (requires `datasyn-code` or stub)                            |
| 4     | LiteLLM        | `make -C infra/litellm up`                                                              |
| 5     | Langfuse       | `make -C infra/langfuse up`                                                             |
| 6     | Brain + UI     | `make -C infra/agent up` or split services                                              |


Full dev stack: start each stack separately (see [`infra/README.md`](../../infra/README.md)).

### 8.3 Production images

Set `ENVIRONMENT=prod`, `DATASYN_IMAGE_REGISTRY=<registry-host:5000>`, push via `make -C infra/distribution publish`, pull via `ENVIRONMENT=prod make -C infra/<stack> up`.

---

## 9. Security and operations (minimum)


| Area            | Requirement                                                                                         |
| --------------- | --------------------------------------------------------------------------------------------------- |
| **Secrets**     | `MINIO_ROOT_`*, `LITELLM_MASTER_KEY`, DB passwords, `OAUTH_*` only in `.env` (gitignored)           |
| **TLS**         | Terminate at reverse proxy (see `infra/litellm/nginx-edge/`) for UI, brain, LiteLLM, Langfuse       |
| **Auth**        | OAuth on brain (`OAUTH_SESSION_SECRET` + Google/GitHub) — see `.env.example`                        |
| **Firewall**    | Expose only UI (8003), Dagster UI (3001), Langfuse (3000) to users; MCP ports to agent subnets only |
| **Backups**     | Snapshot `duckdb_data`, `storage`, `dagster-db-data`, Langfuse volumes daily                        |
| **DuckDB lock** | Never run `duckdb-ui` profile during batch ingest on same `warehouse.duckdb`                        |


---

## 10. Optional: compose-only “all-in-one” dev

For local laptops, all stacks may run on **one host** (see `INSTALL.md`, per-stack `make -C infra/<stack> up`).

---

## 11. References in repo


| Document / path                      | Content                                      |
| ------------------------------------ | -------------------------------------------- |
| `INSTALL.md`                         | Ports, Langfuse, LiteLLM, stack order        |
| `infra/deploy.mk`                    | `ENVIRONMENT`, image prefix, `bootstrap` (included by each stack) |
| `AGENTS.md`                          | Agent tool contracts, ingest rules           |
| `infra/dagster/runtime/dagster.yaml` | Concurrency, per-run CPU/RAM                 |
| `mcp.json`                           | MCP server URLs for brain / IDE              |
| `README.md`                          | Architecture diagrams under `docs/diagrams/` |


---

## 12. Document history


| Version | Date       | Notes                                                             |
| ------- | ---------- | ----------------------------------------------------------------- |
| 1.0     | 2026-05-29 | Initial distributed infra spec (small / medium / high, use cases) |


