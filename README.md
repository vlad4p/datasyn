# 🧠 datasyn

> [English](README.en.md)

> **⚠️ Repositorio en desarrollo activo**
>
> Plataforma **AI-driven** para analizar **datos públicos** sobre infraestructura propia o cloud: warehouse DuckDB, object storage MinIO, orquestación Dagster y agente operativo vía **MCP**.
>
---

## Índice

- [📖 Sobre el proyecto](#sobre-el-proyecto)
- [🏗️ Arquitectura](#arquitectura)
- [🏅 Patrón medalla](#patron-medalla)
- [📦 Layout distribuido](#layout-distribuido)
- [➕ Nueva ingesta (gitflow)](#nueva-ingesta)
- [🔌 Servidores MCP](#servidores-mcp)
- [🔄 Ciclo de una consulta](#ciclo-consulta)
- [💬 Desarrollo con IA](#desarrollo-ia)
- [🚀 Ejecutar en local](#ejecutar-local)
- [📊 Datasets operativos](#datasets)
- [🛠️ Makefile](#makefile)
- [📚 Referencias](#referencias)
- [🤖 Aviso](#aviso)

---

<a id="sobre-el-proyecto"></a>

## 📖 Sobre el proyecto

**datasyn** es la **capa de plataforma**: brain (FastAPI + Deep Agents), UI React, servidores MCP HTTP y stacks Docker (`infra/duckdb`, `infra/object-storage`, `infra/dagster`, registry OCI).

Los **pipelines Dagster** viven en el repo hermano [`datasyn-code`](../datasyn-code). El **runtime Dagster** (webserver, daemon, user code gRPC) se despliega desde `infra/dagster/` en este repo.

El agente no “asiste” en abstracto: **ejecuta** SQL, lista objetos en MinIO y dispara materializaciones Dagster — con trazabilidad (SQL, tool calls, skills versionadas). Los MCP operativos hoy son **`duckdb-mcp`** y **`storage-mcp`**.

**Glosario rápido**

| Término | Significado |
|---------|-------------|
| **Brain** | API FastAPI que orquesta el grafo del agente y los clientes MCP |
| **MCP** | [Model Context Protocol](https://modelcontextprotocol.io/) — contrato HTTP entre IDE/agente y herramientas (`duckdb_*`, `storage_*`) |
| **Skill** | Playbook `SKILL.md` cargado bajo demanda (ingesta, análisis, catálogo) |
| **Code location** | Imagen gRPC Dagster con el paquete `datasyn` (`dagster_user_code`) |
| **Medallion** | Schemas DuckDB `bronze` → `silver` → `gold` |

### Layout del repo (datasyn)

<p align="center"><img src="docs/diagrams/repo-layout.svg" alt="Layout del repositorio datasyn" width="560"/></p>

Raíz: `Makefile` (brain + UI), `mcp.json`, `AGENTS.md`, `docker-compose.yaml` (brain/UI en Docker), `pyproject.toml` + `uv`. Infra Docker: [`infra/README.md`](infra/README.md) y un `Makefile` por stack.

---

<a id="arquitectura"></a>

## 🏗️ Arquitectura

<p align="center"><img src="docs/diagrams/architecture.svg" alt="Arquitectura de plataforma" width="880"/></p>

Cada servicio corre en **su propio contenedor** Docker sobre la red **`infra-datasynk`**. Dos formas de acceder:

| Ruta | Quién | Flujo |
|------|-------|-------|
| **A — agent / UI** | Navegador o cliente HTTP | `ui` (:8003) → `brain` (:8002) → servidores MCP → datos |
| **B — MCP directo** | IDE con cliente MCP | `mcp.json` → `duckdb-mcp` / `storage-mcp` (sin pasar por brain) |

**Observabilidad (opcional):** el contenedor **brain** puede enviar trazas a **[Langfuse](https://langfuse.com/)** (`infra/langfuse/`) — spans de LLM, tool calls MCP y sesiones, visibles en la UI de Langfuse server-side. Ver [`INSTALL.md`](INSTALL.md) (`LANGFUSE_*`).

| Contenedor | Imagen OCI | Rol | Puerto host |
|------------|------------|-----|-------------|
| **brain** | `datasyn/brain` | Grafo Deep Agents, clientes MCP, `AGENTS.md` | `:8002` |
| **ui** | `datasyn/ui` | React; proxy `/api` → brain | `:8003` |
| **duckdb-mcp** | `datasyn/duckdb-mcp` | SQL, schema, listado `/data-local` | `:8040` |
| **storage-mcp** | `datasyn/storage-mcp` | MinIO list/get/put | `:8044` |
| **dagster_*** | `datasyn/dagster-*` | Webserver, daemon, Postgres, gRPC user code | UI `:3001` |
| **MinIO** | `minio/minio` | Object storage `data-local` | `:9000` interno |
| **Langfuse** | stack `infra/langfuse/` | Trazas del brain (opcional) | ver compose |

Reglas operativas del agente: [`AGENTS.md`](AGENTS.md).

---

<a id="patron-medalla"></a>

## 🏅 Patrón medalla

<p align="center"><img src="docs/diagrams/medallion.svg" alt="Patron medalla bronze silver gold" width="420"/></p>

| Schema | Uso en datasyn |
|--------|----------------|
| **bronze** | Landing + tablas crudas (Dagster assets en `datasyn-code`) |
| **silver** | Limpieza y modelos intermedios (mínimo hoy) |
| **gold** | Marts analíticos; excepción INDEC EPH (`gold.indec_eph_*`) |

Implementación de pipelines: repo [`datasyn-code`](../datasyn-code) — ver su README para scrape vs MinIO→CSV.

---

<a id="layout-distribuido"></a>

## 📦 Layout distribuido

Patrón [Dagster distributed code location](https://docs.dagster.io/deployment/overview): runtime en **datasyn**, user code en repo hermano **datasyn-code**.

<p align="center"><img src="docs/diagrams/distributed-layout.svg" alt="Layout distribuido dos repos" width="720"/></p>

```bash
git clone …/datasyn.git
git clone …/datasyn-code.git   # mismo directorio padre

cd datasyn
make -C infra/object-storage bootstrap
make -C infra/object-storage up && make -C infra/duckdb up && make -C infra/dagster up
```

| Repo | Contenido | Comandos clave |
|------|-----------|----------------|
| **datasyn** | Brain, UI, skills, infra (duckdb, minio, Dagster runtime) | `make agent-dev` · stacks en `infra/` · [`INSTALL.md`](INSTALL.md) |
| **datasyn-code** | Assets bronze, jobs, schedules, Dockerfile gRPC | `make dev` · `make push` |

---

<a id="nueva-ingesta"></a>

## ➕ Nueva ingesta (gitflow)

Flujo recomendado para agregar una fuente de datos:

1. **Clonar** [`datasyn`](.) y [`datasyn-code`](../datasyn-code) al mismo nivel; levantar stacks (`infra/README.md`).
2. **Configurar** el entorno del agente: [`mcp.json`](mcp.json), skills en [`skills/`](skills/) (p. ej. [`ingest-scrape-news-bronze`](skills/ingest-scrape-news-bronze/SKILL.md)), [`AGENTS.md`](AGENTS.md).
3. **Desarrollar en gitflow** dentro de **`datasyn-code`**: rama `feature/<fuente>`, assets bajo `src/datasyn/assets/bronze/<fuente>/`, job y schedule; PR → merge a `main`.
4. **Publicar** la code location: `make -C ../datasyn-code push` y redeploy de `dagster_user_code` (ver [`INSTALL.md`](INSTALL.md)).
5. **Validar** en Dagster UI (`:3001`).

El código de pipelines se desarrolla y revisa en **git** dentro de `datasyn-code`; el agente usa **`duckdb_*`** y **`storage_*`** para SQL, landing y validación sobre `/data-local`.

---

<a id="servidores-mcp"></a>

## 🔌 Servidores MCP (datasyn)

Dos contenedores HTTP **FastMCP** — imagen `datasyn/<nombre>-mcp`, un servicio por stack en `infra/`:

| Servidor | Compose | URL típica | Prefijo tools |
|----------|---------|------------|---------------|
| **duckdb-mcp** | `infra/duckdb/` | `http://<host>:8040/mcp` | `duckdb_*` |
| **storage-mcp** | `infra/object-storage/` | `http://<host>:8044/mcp` | `storage_*` |

Configuración de referencia en [`mcp.json`](mcp.json):

```json
{
  "mcpServers": {
    "duckdb":  { "type": "remote", "url": "http://<host>:8040/mcp" },
    "storage": { "type": "remote", "url": "http://<host>:8044/mcp" }
  }
}
```

**Ruta B:** el IDE/cliente MCP apunta `mcp.json` a esas URLs y habla directo con DuckDB o MinIO.

**Ruta A:** el **brain** carga la misma config y reenvía tool calls a esos contenedores cuando el usuario usa la UI o la API del agente.

| Prefijo | Tools principales |
|---------|-------------------|
| `duckdb_*` | `get_schema`, `execute_query`, `list_data_mount` |
| `storage_*` | `list_buckets`, `list_objects`, `get_object_text`, `put_object_*` |

---

<a id="ciclo-consulta"></a>

## 🔄 Ciclo de una consulta

<p align="center"><img src="docs/diagrams/query-flow.svg" alt="Ciclo de una consulta analitica" width="520"/></p>

Ejemplo (Ruta A, EPH hogares):

<p align="center"><img src="docs/diagrams/query-example-chat.svg" alt="Ejemplo de consulta estilo chat EPH hogares" width="560"/></p>

Contrato: **un SQL statement por** `duckdb_execute_query`. Sin inventar columnas — schema primero.

---

<a id="desarrollo-ia"></a>

## 💬 Desarrollo con IA

Skills en [`skills/`](skills/) — playbooks que el brain descubre al arrancar. Para pipelines Dagster y skills de dominio (EPH, catálogo, etc.), ver también [`datasyn-code`](https://github.com/YOUR_ORG/datasyn-code).

| Caso | Skill (datasyn) | Repo de código |
|------|-----------------|----------------|
| Scrape → bronze | [`ingest-scrape-news-bronze`](skills/ingest-scrape-news-bronze/SKILL.md) | `datasyn-code` |
| Subir archivos a MinIO | [`upload_files_storage`](skills/upload_files_storage/SKILL.md) | warehouse / storage MCP |
| EPH, catálogo, otras ingestas | — (playbooks en `AGENTS.md` o `datasyn-code`) | `datasyn-code` |

**Reglas:** [`AGENTS.md`](AGENTS.md) — mandato del agente, paths `/data-local`, disciplina MCP (`duckdb_*`, `storage_*`).

---

<a id="ejecutar-local"></a>

## 🚀 Ejecutar en local

Guía completa: **[`INSTALL.md`](INSTALL.md)** (bootstrap, registry, troubleshooting).

**Stack Docker local (prod-like, brain/ui en contenedor):**

```bash
make -C infra/object-storage bootstrap
make -C infra/object-storage up
make -C infra/duckdb up
make -C infra/dagster up
make -C infra/agent up        # no daily dev — preferir make agent-dev
```

**Desarrollo local (brain `uv` + UI `npm` en host):**

```bash
cp .env.example .env
make uv-sync && make ui-install
make -C infra/object-storage up
make -C infra/duckdb up
make -C infra/dagster up
make agent-dev
```

Publicar user code tras cambios en pipelines:

```bash
make -C ../datasyn-code push
# redeploy: ver INSTALL.md (compose recreate dagster_user_code)
```

---

<a id="datasets"></a>

## 📊 Datasets operativos

Fuentes con pipeline bronze (detalle en [`datasyn-code`](../datasyn-code)):

| Dataset | Grain / notas |
|---------|----------------|
| INDEC EPH | `gold.indec_eph_usu_hogar` / `_individual` — ver skills EPH |
| INDEC Censo 2022 / UCA | Radios censales, CSV UCA |
| Elecciones 2023 generales | Mesas / circuitos |
| Boletín Oficial 3ª sección | Contrataciones diarias |
| Prensa | Infobae, Clarín, La Nación, TN |
| OECD AI Incidents | JSON landing + bronze |

---

<a id="makefile"></a>

## 🛠️ Makefile

**Raíz (`make help`)** — solo brain + UI en el host:

| Comando | Qué hace |
|---------|----------|
| `make uv-sync` | Sincroniza deps Python del brain (`uv sync`) |
| `make ui-install` | `npm install` en `ui/` |
| `make agent-dev` | Brain `:8002` + Vite `:5173` (uv + npm en host) |
| `make agent-brain` | Solo brain (`uv run brain-dev`) |
| `make test-agent` | `uv run pytest` |
| `make brain-restart` | Mata `:8002` y reinicia brain |

**Infra Docker** — un `Makefile` por stack ([`infra/README.md`](infra/README.md)):

| Comando | Qué hace |
|---------|----------|
| `make -C infra/object-storage bootstrap` | Red `infra-datasynk` + volúmenes |
| `make -C infra/object-storage up` | MinIO + storage-mcp |
| `make -C infra/duckdb up` | DuckDB + duckdb-mcp |
| `make -C infra/dagster up` | Dagster runtime |
| `make -C infra/agent up` | Brain + UI en contenedores (prod-like) |
| `make -C infra/distribution publish …` | Push imágenes (`ENVIRONMENT=prod`) |

Flujo diario:

```bash
make -C infra/object-storage up && make -C infra/duckdb up && make -C infra/dagster up
make agent-dev
```

Variables infra: `ENVIRONMENT` (`dev`|`prod`), `DATASYN_IMAGE_REGISTRY` (prod). Ver [`INSTALL.md`](INSTALL.md).

---

<a id="referencias"></a>

## 📚 Referencias

| Tema | Enlace |
|------|--------|
| Instalación y deploy | [`INSTALL.md`](INSTALL.md) |
| Publicar / seguridad | [`docs/PUBLISHING.md`](docs/PUBLISHING.md) · [`SECURITY.md`](SECURITY.md) |
| Agente warehouse | [`AGENTS.md`](AGENTS.md) |
| Skills | [`skills/`](skills/) |
| Diagramas (SVG) | [`docs/diagrams/`](docs/diagrams/) |
| Pipelines Dagster | [`../datasyn-code`](../datasyn-code) |
| MCP spec | https://modelcontextprotocol.io/ |
| DuckDB | https://duckdb.org/ |
| Dagster AI-driven DE | https://dagster.io/blog/announcing-ai-driven-data-engineering |

---

<a id="aviso"></a>

## 🤖 Aviso

Este repositorio fue creado mediante *vibe coding* 🤖 con [Cursor](https://cursor.com) y modelos de [Anthropic](https://www.anthropic.com).

Este proyecto se apoya en un concepto de almacenado y procesamiento **distribuido** mediante instrucciones en **lenguaje natural**, como paso hacia una **descentralización** de la información necesaria para tomar decisiones.