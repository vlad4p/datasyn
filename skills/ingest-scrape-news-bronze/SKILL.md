---
name: ingest-scrape-news-bronze
description: >-
  Scrape public news or opinion pages (HTTP + HTML), land markdown in MinIO,
  ingest rows into DuckDB schema bronze with article metadata. Use when adding
  a media source, Dagster bronze assets for web scraping, TN/Infobae/La Nación
  style pipelines, or ingesta de noticias desde una URL o listado.
---

# Ingesta bronze desde scraping web (noticias / opinión)

Playbook para sumar una **fuente HTML pública** al warehouse: **scrape → landing MinIO (markdown + frontmatter) → tabla `bronze.*` en DuckDB**, con pipeline Dagster particionado por día.

Referencias canónicas en **este repo**:

| Medio | `lib.py` | `assets.py` | Job |
|-------|----------|-------------|-----|
| TN | `src/datasyn/assets/bronze/tn/lib.py` | `tn/assets.py` | `jobs/tn_job.py` → `tn_backfill_job` |
| Infobae | `infobae/lib.py` | `infobae/assets.py` | `jobs/infobae_job.py` |
| La Nación | `lanacion/lib.py` | `lanacion/assets.py` | `jobs/lanacion_job.py` |
| La Nación opinión | `lanacion/opinion_lib.py` | `lanacion/opinion_assets.py` | `jobs/lanacion_opinion_job.py` |

Prompt listo para copiar: [`prompts/add-bronze-scrape-source.txt`](../../prompts/add-bronze-scrape-source.txt).

---

## Cuándo usar esta skill

- El usuario pide **ingerir noticias**, **scrapear un medio**, **nueva fuente de prensa**, o **tabla bronze** desde páginas HTML.
- Vas a crear assets bajo `src/datasyn/assets/bronze/<fuente>/`.

**No** uses este playbook para CSV ya en MinIO — ver [`skills/add-bronze-minio-csv/SKILL.md`](../add-bronze-minio-csv/SKILL.md).

---

## Arquitectura (obligatoria)

```text
Hub / listado HTML  →  enlaces del día  →  GET artículo  →  ArticleDoc
       ↓
MinIO  landing/<fuente>/<tema>/YYYY/MM/DD/<slug>.md   (frontmatter YAML + cuerpo)
       ↓
Dagster asset bronze  →  DELETE día + INSERT  →  bronze.<fuente>_noticias
```

Opcional: **Iceberg REST** si `ICEBERG_REST_ENDPOINT` está configurado (`attach_iceberg_catalog`).

---

## 1. Scraping (`lib.py`)

- `httpx.Client` con User-Agent de navegador, `Accept-Language: es-AR,es`, timeout ~30s.
- Pausa entre requests (`sleep_s` ~0.35); loguear y seguir si un artículo falla.
- Documentar el criterio de fecha por sitio (path, `article:published_time`, etc.).
- Frontmatter mínimo: `tema`, `title`, `url`, `fecha_publicacion`, `scraped_at`, `landing_key`.
- Clave MinIO: `landing/<fuente>/<tema>/YYYY/MM/DD/<slug>.md`.

`lib.py` **puede** usar `from __future__ import annotations`.

---

## 2. Dagster assets (`assets.py`)

### Estructura

```text
src/datasyn/assets/bronze/<fuente>/
  __init__.py
  lib.py
  assets.py
src/datasyn/jobs/<fuente>_job.py
```

### Particiones

`DailyPartitionsDefinition(start_date=..., end_offset=1)` — una partición = día de **publicación**.

### Dos assets

1. **`<fuente>_landing_markdown`** — scrape → `put_object` MinIO.
2. **`<fuente>_noticias_bronze`** — `deps=[landing]`, parsea frontmatter, escribe DuckDB.

### Esquema bronze

```sql
CREATE TABLE IF NOT EXISTS bronze.<fuente>_noticias (
    tema VARCHAR,
    titulo VARCHAR,
    url VARCHAR,
    cuerpo_md VARCHAR,
    fecha_publicacion TIMESTAMP,
    scraped_at TIMESTAMP,
    landing_key VARCHAR
);
```

Idempotencia por día:

```sql
DELETE FROM bronze.<fuente>_noticias
WHERE CAST(fecha_publicacion AS DATE) = DATE '<partition_key>';
-- luego INSERT filas del landing de ese día
```

### CRÍTICO — `from __future__ import annotations`

| Archivo | ¿Usar future annotations? |
|---------|----------------------------|
| `lib.py` | Sí (opcional) |
| **`assets.py`** con `database: DuckDBResource` | **NO** |

---

## 3. Registro

1. **`definitions.py`** — agregar módulo a `load_assets_from_modules([..., bronze_<fuente>])`.
2. **`jobs/<fuente>_job.py`** — exportar símbolo `<fuente>_job` (mismo nombre que el archivo). El job se auto-registra vía `collect_named(jobs)`; **no** editar la lista de jobs en `definitions.py`.

```python
define_asset_job(
    name="<fuente>_backfill_job",
    selection=AssetSelection.assets(landing_asset, bronze_asset),
    partitions_def=..._DAILY,
    description="Scrape → MinIO → bronze.<fuente>_noticias",
)
```

---

## 4. Validación

```bash
make dev
```

Materializar una partición de prueba en la UI. Convenciones: `group_name="bronze"`, `compute_kind="python"`, `MaterializeResult` con metadata, `Failure` para errores visibles.

---

## Checklist de cierre

- [ ] Hub y patrón de fecha documentados en `lib.py`
- [ ] Frontmatter con metadatos de artículo
- [ ] `assets.py` **sin** `from __future__ import annotations`
- [ ] Módulo en `definitions.py` + job en `jobs/<fuente>_job.py`
- [ ] `make dev` carga sin errores
- [ ] Solo información pública (repo público)

---

## Anti-patrones

- Scrape directo a bronze sin landing.
- `from __future__ import annotations` en `assets.py` con `DuckDBResource`.
- Agregar Compose, MCP servers o infra a este repo.
- Romper convención `collect_named`: nombre de archivo = símbolo exportado.
