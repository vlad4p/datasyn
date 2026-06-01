# INSTALL — DataSyn

Despliegue del stack DataSyn (brain + UI + plataforma de datos + servidores MCP).

- Qué hace cada pieza: [`README.md`](README.md)
- Agente y SQL: [`AGENTS.md`](AGENTS.md)
- Variables de deploy: [`infra/deploy.mk`](infra/deploy.mk) (incluido por cada `infra/*/Makefile`)

---

## Requisitos

| Herramienta | Uso |
|---|---|
| Docker + Compose v2 | Infra + MCP en contenedor (MinIO, DuckDB, Dagster) |
| Make | **`Makefile` raíz** (brain + UI) + **`infra/*/Makefile`** (un deploy por stack) |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | **Brain en host:** `make uv-sync`, `uv run brain-dev` |
| Node.js + npm | **UI en host:** `make ui-install`, `npm run dev` en `ui/` |

**Repo hermano (pipelines Dagster):** clonar [`datasyn-code`](../datasyn-code) al lado de `datasyn/` (`../datasyn-code`). Sin él, Dagster usa un stub vacío en `infra/dagster/user_code/`.

---

## `ENVIRONMENT`: dev vs prod

Un solo conjunto de targets Make; el modo lo define **`ENVIRONMENT`** (en cada `infra/*/Makefile`, vía [`infra/deploy.mk`](infra/deploy.mk)):

| | `ENVIRONMENT=dev` (default) | `ENVIRONMENT=prod` |
|---|---|---|
| **Imágenes** | `docker compose build` en tu máquina | `docker compose pull` desde registry |
| **Prefijo de tag** | `datasyn/<servicio>:latest` | `<registry>/datasyn/<servicio>:latest` |
| **Registry OCI** | No se usa | Obligatorio: `DATASYN_IMAGE_REGISTRY=host:port` |
| **Ejemplo de tag** | `datasyn/brain:latest` | `registry.example.com:5000/datasyn/brain:latest` |

Comprobar resolución:

```bash
make -C infra/distribution print-env
make -C infra/distribution print-env ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
```

Variables útiles:

| Variable | Default (dev) | Prod |
|---|---|---|
| `ENVIRONMENT` | `dev` | `prod` |
| `DATASYN_IMAGE_PREFIX` | `datasyn` (auto) | `$DATASYN_IMAGE_REGISTRY/datasyn` (auto) |
| `DATASYN_IMAGE_TAG` | `latest` | `latest` |
| `DATASYN_IMAGE_REGISTRY` | — | `host:port` o derivado de `REGISTRY_HTTP_URL` |
| `DATASYN_CODE_DIR` | `../datasyn-code` | igual |

---

## Puertos (host)

| Servicio | Puerto | Notas |
|---|---|---|
| Brain (FastAPI) | `8002` | **Host** con `make agent-dev` (`uv run brain-dev`) |
| UI | `5173` | **Host** con `make agent-dev` (`npm run dev`) |
| UI (contenedor) | `8003` | Solo con `make -C infra/agent up` (no daily dev) |
| Dagster UI | `3001` | |
| MinIO consola | `9001` | |
| `duckdb-mcp` | `8040` | `mcp.json` → `duckdb` |
| `storage-mcp` | `8044` | `mcp.json` → `storage` |
| **Langfuse UI** | `3000` | Opcional: `make -C infra/langfuse-deploy up` |
| DuckDB Local UI | `4213` | Perfil `ui`; opcional |
| Registry OCI | `5000` | `make -C infra/distribution up` + `make -C infra/distribution publish`; **no** en dev local |

En macOS, el puerto **5000** suele estar ocupado por AirPlay. Para un registry local: `REGISTRY_PUBLISH_PORT=5001` y `DATASYN_IMAGE_REGISTRY=localhost:5001` (añadir a Docker **insecure-registries**).

---

## Quick start — desarrollo local (recomendado)

**Brain y UI en el host** (`uv` + `npm`). **Infra en Docker** (MinIO, DuckDB, Dagster, MCPs). No uses `make -C infra/agent up` para el día a día — levanta brain/UI en contenedores.

### Primera vez

```bash
cp .env.example .env          # LLM, OAuth, MCP
make uv-sync                  # Python → .venv (uv)
make ui-install               # deps en ui/ (npm)
```

### Cada sesión

```bash
make -C infra/object-storage bootstrap   # red + volúmenes (primera vez)
make -C infra/object-storage up
make -C infra/duckdb up
make -C infra/dagster up
make agent-dev                           # host: uv brain :8002 + npm Vite :5173
```

| Qué | Dónde | URL |
|---|---|---|
| UI (Vite) | **host** (`npm run dev`) | http://127.0.0.1:5173 |
| Brain (FastAPI) | **host** (`uv run brain-dev`) | http://127.0.0.1:8002 |
| Dagster | Docker | http://127.0.0.1:3001 |
| MinIO consola | Docker | http://127.0.0.1:9001 |
| duckdb-mcp / storage-mcp | Docker | :8040 / :8044 |

Parar infra:

```bash
make -C infra/object-storage down
make -C infra/duckdb down
make -C infra/dagster down
# brain/vite: Ctrl+C en la terminal de agent-dev
```

Solo brain en host (sin UI):

```bash
make -C infra/object-storage up && make -C infra/duckdb up && make -C infra/dagster up && make agent-brain
```

### Stack completo en Docker (prod-like, no daily dev)

Brain y UI **en contenedores** — útil para probar imágenes `datasyn/*` como en prod:

```bash
make -C infra/object-storage up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/duckdb up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/dagster up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/agent up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
```

Por stack:

```bash
make -C infra/object-storage up
make -C infra/duckdb up
make -C infra/dagster up
```

### User code Dagster (`datasyn-code`)

```bash
# Desde datasyn (detecta ../datasyn-code o usa stub):
make -C infra/dagster user-code-build

# Desde el repo hermano:
cd ../datasyn-code && make build ENVIRONMENT=dev
```

Recrear tras cambios:

```bash
make -C infra/dagster user-code-build
docker compose -f infra/dagster/docker-compose.yaml up -d --force-recreate dagster_user_code
```

---

## Quick start — producción (`ENVIRONMENT=prod`)

En un servidor (o laptop) que **tira** imágenes ya publicadas:

```bash
export DATASYN_IMAGE_REGISTRY=registry.example.com:5000   # host:port del registry, sin http://

make -C infra/object-storage bootstrap
make -C infra/object-storage up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/duckdb up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/dagster up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make -C infra/agent up ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
```

### Publicar imágenes al registry

Desde una máquina de build (p. ej. CI o laptop):

```bash
# Build + push (compose push; puede requerir insecure-registries si el registry es HTTP local)
make -C infra/distribution publish ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000

# Registry local en Docker (opcional, puerto 5000/5001):
make -C infra/distribution up REGISTRY_PUBLISH_PORT=5001
make -C infra/distribution publish ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=localhost:5001

# Push a registry HTTP sin tocar Docker Engine (Skopeo + buildx):
make -C infra/distribution publish-remote ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
```

User code de pipelines:

```bash
cd ../datasyn-code
make build ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
make push ENVIRONMENT=prod DATASYN_IMAGE_REGISTRY=registry.example.com:5000
```

---

## Compose sin Make (solo infra en dev local)

Brain y UI: **`uv run brain-dev`** y **`cd ui && npm run dev`** — no levantes `docker-compose.yaml` raíz en daily dev.

```bash
docker network create infra-datasynk 2>/dev/null || true
docker volume create duckdb_data storage 2>/dev/null || true

export ENVIRONMENT=dev
export DATASYN_IMAGE_PREFIX=datasyn
export DATASYN_IMAGE_TAG=latest
export DATASYN_CODE_DIR=/ruta/a/datasyn-code

docker compose -f infra/object-storage/docker-compose.yaml up -d --build
docker compose -f infra/duckdb/docker-compose.yaml up -d --build
docker compose -f infra/dagster/docker-compose.yaml up -d --build

cp .env.example .env && uv sync && cd ui && npm install
uv run brain-dev          # terminal 1
cd ui && npm run dev        # terminal 2
```

Prod (pull):

```bash
export ENVIRONMENT=prod
export DATASYN_IMAGE_REGISTRY=registry.example.com:5000
export DATASYN_IMAGE_PREFIX=$DATASYN_IMAGE_REGISTRY/datasyn

docker compose -f infra/object-storage/docker-compose.yaml pull
docker compose -f infra/object-storage/docker-compose.yaml up -d
# … mismo patrón para duckdb, dagster, docker-compose.yaml raíz
```

---

## Archivos de entorno

| Archivo | Stack |
|---|---|
| `.env` (raíz) | Brain en host: LLM, OAuth, MCP |
| `compose.env` | Brain en contenedor |
| `infra/object-storage/.env` | MinIO (`cp .env.example`) |
| `infra/dagster/.env` | Dagster user code / runs (LiteLLM, MinIO, paths) |
| `infra/duckdb/mcp/.env` | Opcional, duckdb-mcp |
| `mcp.json` | URLs MCP para el brain |

---

## Brain y UI en host (`uv` + `npm`)

Flujo diario: **no** contenedores `brain` / `ui`. Solo infra en Docker.

| Comando | Qué hace |
|---|---|
| `make uv-sync` | `uv sync` — deps Python en `.venv` |
| `make ui-install` | `npm install` en `ui/` |
| `make agent-dev` | `uv run brain-dev` (:8002) + `npm run dev` (:5173) en paralelo |
| `make agent-brain` | Solo brain en host |
| `make brain-restart` | Mata :8002 y relanza `brain-dev` |
| `make test-agent` | `uv run pytest tests/` |

`.env` en la raíz alimenta al brain en host (LLM, OAuth, MCP). `compose.env` solo aplica si corrés brain en contenedor (`make -C infra/agent up`).

MCP en Docker + brain en host: URLs de `mcp.json` se reescriben a `127.0.0.1:8040` / `8044`. Remotos: `MCP_DISABLE_HOST_URL_REWRITE=1`.

---

## Langfuse (trazas del agente, opcional)

Stack upstream en **`infra/langfuse/`** (repo Langfuse). Levántalo aparte con `make -C infra/langfuse-deploy up`.

### 1. Arrancar Langfuse

```bash
make -C infra/langfuse-deploy up
# equivalente:
# cp infra/langfuse-deploy/.env.datasyn.example infra/langfuse/.env
#   # or: make -C infra/langfuse-deploy init-env
# docker compose -f infra/langfuse/docker-compose.yml --env-file infra/langfuse/.env up -d
```

- UI: http://127.0.0.1:3000  
- Login inicial (`.env.datasyn.example`): `admin@example.com` / `datasyn-local`  
- Proyecto pre-creado: **datasyn-brain** con claves fijas de dev (ver abajo).

**Puertos en localhost:** 3000 (UI), 3030 (worker), 5432 (Postgres), 6379 (Redis), 8123/9000 (ClickHouse), 9090/9091 (MinIO interno de Langfuse). Dagster sigue en **:3001** para no chocar con la UI de Langfuse.

### 2. Configurar el brain (host `uv`)

En la raíz, en **`.env`** (mismas claves que `LANGFUSE_INIT_PROJECT_*` en `infra/langfuse/.env`):

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-datasyn-local-dev
LANGFUSE_SECRET_KEY=sk-lf-datasyn-local-dev
LANGFUSE_BASE_URL=http://127.0.0.1:3000
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:3000/api/public/otel
OTEL_SERVICE_NAME=datasyn-brain
DEPLOYMENT_ENV=dev
```

Reiniciar el brain tras editar `.env`:

```bash
make brain-restart
# o Ctrl+C en agent-dev y volver a lanzar
```

### 3. Verificar

```bash
curl -s http://127.0.0.1:8002/api/health | jq '.langfuse_tracing_enabled'
# true

# Tras un mensaje en el chat del agente, abrir Langfuse → Traces
```

El brain envía trazas por **Langfuse SDK** (`CallbackHandler` en `/agent/chat`) y por **OTLP** si `OTEL_EXPORTER_OTLP_ENDPOINT` está definido (auth Basic desde las mismas claves).

**Brain en contenedor** (`make -C infra/agent up`): usa `http://host.docker.internal:3000` para `LANGFUSE_BASE_URL` y OTLP (ver `compose.env`).

Parar Langfuse: `make langfuse-down`.

---

## Backends de modelo

`MODEL_PROVIDER` en `compose.env` o `.env`:

| Valor | Requerido | Notas |
|---|---|---|
| `litellm` | `LITELLM_KEY`, `LITELLM_PROXY_BASE`, `CHAT_MODEL` | `infra/litellm/` |
| `openrouter` | `OPENROUTER_API_KEY`, `CHAT_MODEL` | |
| `gemini` | `GEMINI_API_KEY` o `GOOGLE_API_KEY` | |

Langfuse opcional: `LANGFUSE_*` en `compose.env`. Brain en Docker hacia LiteLLM en host: `http://host.docker.internal:4000` o `LITELLM_DOCKER_HOST_REWRITE=1`.

---

## Imágenes y registry (referencia Make)

| Target | Uso |
|---|---|
| `make agent-dev` | Brain + UI en host (uv + npm) — **Makefile raíz** |
| `make -C infra/object-storage up` | MinIO + storage-mcp |
| `make -C infra/duckdb up` | DuckDB + duckdb-mcp |
| `make -C infra/dagster up` | Dagster runtime |
| `make -C infra/object-storage mcp-up` | Solo MCP storage |
| `make -C infra/duckdb mcp-up` | Solo MCP duckdb |
| `make -C infra/agent up` | Brain + UI en Docker (:8002, :8003) |
| `make -C infra/distribution images-build` | Build imágenes `datasyn/*` |
| `make -C infra/distribution publish …` | Push al registry (`ENVIRONMENT=prod`) |
| `make -C infra/langfuse-deploy up` | Langfuse :3000 (opcional) |

Listado: `make help` (raíz) · [`infra/README.md`](infra/README.md) · `make -C infra/<stack> help`.

---

## DuckDB Local UI (opcional)

Perfil Compose `ui`. **Bloquea `warehouse.duckdb`** — no usar durante ingest.

```bash
make -C infra/duckdb ui-up      # http://127.0.0.1:4213
make -C infra/duckdb ui-down
# alias raíz:
make infra-duckdb-ui-up
make infra-duckdb-ui-down
```

---

## Catálogo y UI

- **Datasets (UI):** `GET /api/catalog/datasets` — fusiona DuckDB + Dagster GraphQL (`DAGSTER_URL`, default `http://127.0.0.1:3001`).
- **MCP catálogo:** `dagster_catalog_*` en `mcp.json` si hay Postgres de metadatos; ver `skills/catalog-sql/`.
- **Análisis exportados:** `./reports/analyses/` (montado en brain como `/project/reports`).

---

## Verificación rápida

```bash
make -C infra/distribution print-env
make infra-ps

curl -s http://127.0.0.1:8002/api/health | jq .
curl -s http://127.0.0.1:8002/api/health/tools | jq '.tools | length'
open http://127.0.0.1:5173    # UI host (make agent-dev)
```

| URL | Servicio |
|---|---|
| http://127.0.0.1:5173 | UI Vite (`make agent-dev`) |
| http://127.0.0.1:8002 | Brain |
| http://127.0.0.1:8003 | UI contenedor |
| http://127.0.0.1:3001 | Dagster |
| http://127.0.0.1:9001 | MinIO consola |

Tests (sin MCP):

```bash
uv run pytest tests/ -q
```

---

## Troubleshooting

| Síntoma | Causa | Mitigación |
|---|---|---|
| `bind: address already in use` en `:5000` | AirPlay (macOS) u otro proceso | `REGISTRY_PUBLISH_PORT=5001` o desactivar Receptor AirPlay |
| `stack-up` / brain en Docker | Conflicto de puertos con host | `make -C infra/agent down` luego stacks `up` + `make agent-dev` |
| `pull access denied` / `repository does not exist` | Imagen no construida (dev) o no publicada (prod) | Dev: `make -C infra/distribution images-build` o `up` por stack. Prod: `make -C infra/distribution publish` |
| `Could not set lock` (DuckDB) | DuckDB UI abierta | `make -C infra/duckdb ui-down` |
| `InvalidAccessKeyId` (storage-mcp) | Endpoint/credenciales MinIO | Host `datasyn-object-minio:9000`; alinear con `infra/object-storage/.env` |
| Brain no alcanza MCP (`agent-dev`) | Hostnames Docker en `mcp.json` | `make -C infra/object-storage mcp-up` y `make -C infra/duckdb mcp-up` |
| `dagster_user_code` unhealthy | Imagen vieja o sin build | `make -C infra/dagster user-code-build` y `--force-recreate dagster_user_code` |
| LiteLLM `ConnectError` desde brain en Docker | `127.0.0.1` en contenedor | `host.docker.internal:4000` o `LITELLM_DOCKER_HOST_REWRITE=1` |
| Cambios en `dagster.yaml` ignorados | Solo en imagen | Bind mount ya en webserver/daemon; reiniciar servicios |

---

## Secretos

No commitear `.env`, claves (`*.pem`), ni `data-local/` / `*.duckdb`. Ver `.gitignore`.

---

## Referencias

| Recurso | Contenido |
|---|---|
| [`Makefile`](Makefile) | Targets raíz; `make help` |
| [`infra/deploy.mk`](infra/deploy.mk) | `ENVIRONMENT`, prefijos, `bootstrap` (incluido por cada stack) |
| [`infra/README.md`](infra/README.md) | Índice de stacks y orden de arranque |
| `infra/*/Makefile` | Deploy por stack |
| [`../datasyn-code/Makefile`](../datasyn-code/Makefile) | Build/push user code |
| [`mcp.json`](mcp.json) | Servidores MCP |
| [`compose.env`](compose.env) | Variables brain en contenedor |
