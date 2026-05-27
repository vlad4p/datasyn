# INSTALL — DataSyn

Despliegue del stack DataSyn (brain + UI + plataforma de datos + servidores MCP).

Para qué hace cada componente y cómo se usa, ver [`README.md`](README.md). Para reglas operativas del agente y reglas de SQL, ver [`AGENTS.md`](AGENTS.md).

---

## Requisitos

- Docker + Docker Compose v2
- Make (recomendado)
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — gestor de Python del brain (local: siempre `uv sync` / `uv run`, no `pip` ni `python` sueltos)
- Node.js — solo para la UI en host (`npm run dev`)

Puertos publicados por defecto:

| Servicio | Puerto host | Servicio MCP |
|---|---|---|
| UI (Vite servida en container) | `8003` | — |
| Brain (FastAPI) | `8002` | — |
| Dagster webserver | `3001` | — |
| MinIO (consola) | `9001` | — |
| MinIO (S3 API) | interno | — |
| `duckdb-mcp` | `8040` | `duckdb` |
| `dagster-mcp` | `8043` | `dagster` |
| `storage-mcp` | `8044` | `storage` |
| Registry OCI (`registry:3`) | `5000` | — |

---

## Quick start

```bash
make bootstrap        # red infra-datasynk + volúmenes duckdb_data, storage
make images-prepare   # registry local + build de todas las imágenes
make infra-up         # MinIO, DuckDB+MCP, Dagster+MCP
make agent-up         # brain + UI
```

`make stack-up` = `infra-up` + `agent-up`. `make help` lista todos los targets.

### Compose-only (sin Make)

```bash
docker network create infra-datasynk 2>/dev/null || true
docker volume create duckdb_data 2>/dev/null || true
docker volume create storage 2>/dev/null || true

export DATASYN_IMAGE_REGISTRY=localhost:5000
export DATASYN_IMAGE_NAMESPACE=datasyn
export DATASYN_IMAGE_TAG=latest

docker compose -f infra/distribution/docker-compose.yaml up -d
docker compose -f infra/object-storage/docker-compose.yaml up -d
docker compose -f infra/duckdb/docker-compose.yaml up -d
docker compose -f infra/dagster/docker-compose.yaml up -d
docker compose up -d
```

---

## Desarrollo del brain en host

Requisito: [uv](https://docs.astral.sh/uv/getting-started/installation/) instalado. Python lo fija `.python-version` (3.12); `uv sync` crea `.venv`.

```bash
cp .env.example .env          # LLM + MCP (editar OPENROUTER_API_KEY u otro provider)
uv sync                       # instala deps en .venv
make agent-dev                # uv run brain-dev :8002 + Vite :5173
```

Solo brain (sin UI):

```bash
make agent-brain              # equivalente a: uv run brain-dev
```

MCP local en Docker (opcional; si usás un servidor remoto, configurá `mcp.json` y `MCP_DISABLE_HOST_URL_REWRITE=1` en `.env`):

```bash
make mcp-up
make agent-dev
```

En modo host con MCP en Docker, las URLs de `mcp.json` (`duckdb-mcp`, …) se reescriben a `127.0.0.1:8040 / 8044 / 8043`. Para URLs externas (IP/hostname): `MCP_DISABLE_HOST_URL_REWRITE=1`.

---

## Backends de modelo

`MODEL_PROVIDER` en `compose.env` o `.env`:

| Valor | Requerido | Notas |
|---|---|---|
| `litellm` | `LITELLM_KEY`, `LITELLM_PROXY_BASE`, `CHAT_MODEL` | Proxy auto-hosteado (`infra/litellm/`); `CHAT_MODEL` debe existir en `GET /v1/models` |
| `openrouter` | `OPENROUTER_API_KEY`, `CHAT_MODEL` | Slug de OpenRouter; opcional `OPENROUTER_BASE_URL` |
| `gemini` | `GEMINI_API_KEY` (o `GOOGLE_API_KEY`) | `CHAT_MODEL` opcional (default `gemini-2.0-flash`) |

Trazas opcionales con Langfuse (`infra/langfuse/`): `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`. Detalle de loopback host/Docker en `compose.env`.

---

## Imágenes y registry

Tags: `${DATASYN_IMAGE_REGISTRY}/${DATASYN_IMAGE_NAMESPACE}/<servicio>:${DATASYN_IMAGE_TAG}` (default `localhost:5000/datasyn/...:latest`).

| Target | Acción |
|---|---|
| `make images-build` | Build local (todos los compose) |
| `make images-push` | Push al registry local |
| `make publish` | `images-prepare` + `images-push` |
| `make images-build-remote DATASYN_IMAGE_REGISTRY=<host:port>` | Build con `DOCKER_DEFAULT_PLATFORM=linux/amd64` (Apple Silicon → server x86) |
| `make publish-remote DATASYN_IMAGE_REGISTRY=<host:port>` | Build + push a registry externo (Skopeo, sin `insecure-registries`) |
| `make storage-mcp-build-push-remote` | Cross-build buildx + push de `storage-mcp` |
| `make dagster-user-code-build-push-remote` | Idem para `dagster_user_code_image` |

Para registries HTTP: agregar host:port a `insecure-registries` del Docker Engine, **o** usar los targets `*-remote` que evitan ese requisito.

---

## DuckDB Local UI (opcional)

Behind compose `profile: ui`. **Mantiene un lock sobre `warehouse.duckdb`** mientras corre, así que no la dejes prendida durante ingest.

```bash
make infra-duckdb-ui-up    # http://127.0.0.1:4213
make infra-duckdb-ui-down
```

---

## Catálogo de metadatos (opcional)

Si tu organización tiene un catálogo (Postgres con descripciones de columnas, lineage, tags), exportá `DATABASE_URL` o `CATALOG_DATABASE_URL` en `infra/dagster/.env`. `dagster-mcp` expone `dagster_catalog_get_schema` y `dagster_catalog_execute_query`. El agente prioriza catálogo antes de tocar archivos. Patrones de SQL en `skills/catalog-sql/SKILL.md` (cuando se incorpore).

---

## Verificación rápida

```bash
make infra-ps              # estado de containers de infra
make agent-ps              # estado de brain + UI
make registry-api-v2       # GET /v2/ del registry
curl -s http://localhost:8002/api/health        | jq .       # brain
curl -s http://localhost:8002/api/health/tools  | jq '.tools | length'   # tools MCP cargadas
```

UI: `http://localhost:8003` · Dagster: `http://localhost:3001` · MinIO console: `http://localhost:9001`.

---

## Troubleshooting

| Síntoma | Causa | Mitigación |
|---|---|---|
| `Could not set lock` / IO error de DuckDB | DuckDB Local UI mantiene la DB abierta | `make infra-duckdb-ui-down` o evitar `--profile ui` durante ingest |
| `InvalidAccessKeyId` desde `storage-mcp` | Endpoint o credenciales MinIO incorrectos | Usar alias `http://datacyber-object-minio:9000`; alinear `MINIO_ROOT_*` con `infra/object-storage/.env` |
| Brain no alcanza MCP en `make agent-dev` | URL de `mcp.json` apunta a hostname Docker | El brain reescribe a `127.0.0.1:8040/43/44`; verificar `make mcp-up` |
| `dagster_user_code` no levanta | Imagen stale tras cambio de assets | `make dagster-user-code-image` y recrear el servicio |
| `ConnectError` desde brain a LiteLLM (Docker) | `LITELLM_PROXY_BASE` apunta a loopback | Usar `http://host.docker.internal:4000` o `LITELLM_DOCKER_HOST_REWRITE=1` |
| `dagster.yaml` no toma cambios | Solo COPY en imagen, no bind | Verificar bind mount en `dagster_webserver` / `dagster_daemon` |

---

## `.gitignore` y secretos

No commitear:

- `.env` / `.env.*` (excepto `*.env.example`)
- Claves privadas: `*.pem`, `*.p12`, `*.pfx`, material SSH
- Datos locales: `data-local/`, `*.duckdb`

Si se filtró una clave: rotarla y limpiar historia (`git filter-repo`, BFG).

---

## Referencias

- [`Makefile`](Makefile) — `make help` para la lista completa.
- [`AGENTS.md`](AGENTS.md) — contrato del agente, reglas DuckDB, antipatrones.
- [`mcp.json`](mcp.json) — URLs de los servidores MCP.
- [`compose.env`](compose.env) — variables del brain (LiteLLM, OpenRouter, Gemini, Langfuse).
