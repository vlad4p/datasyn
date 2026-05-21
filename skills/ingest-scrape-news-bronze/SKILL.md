---
name: ingest-scrape-news-bronze
description: >-
  Scrape news or opinion pages (HTTP + HTML), land markdown in MinIO, ingest rows
  into DuckDB schema bronze with article metadata. Use when adding a media source,
  Dagster bronze assets for web scraping, lanacion/infobae-style pipelines, or
  ingesta de noticias desde una URL o listado.
---

# Ingesta bronze desde scraping web (noticias / opinión)

Playbook para sumar una **fuente HTML** (diario, sección, columnistas) al warehouse: **scrape → landing MinIO (markdown + frontmatter) → tabla `bronze.*` en DuckDB**, con **metadatos por artículo** y pipeline Dagster particionado por día.

Referencias canónicas en el repo:

| Medio | `lib.py` (scrape) | `assets.py` (Dagster) | Job |
|-------|-------------------|----------------------|-----|
| Infobae | `datasyn/assets/bronze/infobae/lib.py` | `infobae/assets.py` | `infobae_backfill_job` |
| La Nación noticias | `datasyn/assets/bronze/lanacion/lib.py` | `lanacion/assets.py` | `lanacion_backfill_job` |
| La Nación opinión | `datasyn/assets/bronze/lanacion/opinion_lib.py` | `lanacion/opinion_assets.py` | `lanacion_opinion_backfill_job` |

---

## Cuándo usar esta skill

- El usuario pide **ingerir noticias**, **scrapear un medio**, **nueva fuente de prensa**, o **tabla bronze** desde páginas HTML.
- Vas a crear o modificar assets bajo `infra/dagster/mcp/dagster-code/projects/datasyn/src/datasyn/assets/bronze/<fuente>/`.
- Necesitás validar filas en DuckDB (`duckdb_execute_query`) después de un backfill.

**No** uses este playbook para INDEC EPH (`gold.indec_eph_*`) ni para cargas CSV bajo `/data-local` sin scrape — ver `ingest-indec-mercadolaboral` y reglas genéricas en `AGENTS.md`.

---

## Arquitectura (obligatoria)

```text
Hub / listado HTML  →  enlaces del día  →  GET artículo  →  ArticleDoc
       ↓
MinIO  landing/<fuente>/<tema>/YYYY/MM/DD/<slug>.md   (frontmatter YAML + cuerpo)
       ↓
Dagster asset bronze  →  DELETE día + INSERT  →  bronze.<fuente>_noticias
```

Opcional: **Iceberg REST** si `ICEBERG_REST_ENDPOINT` está configurado (mismo patrón que `attach_iceberg_catalog` en assets existentes).

---

## 1. Scraping (lib)

### Cliente HTTP

- `httpx.Client` con `User-Agent` de navegador, `Accept-Language: es-AR,es`, timeout ~30s, `follow_redirects=True`.
- Pausa entre requests (`sleep_s` ~0.35) para no saturar el origen.
- Loguear y **seguir** con la siguiente URL si un artículo falla; no abortar todo el run.

### Descubrir URLs del día

Elegir **un** criterio de fecha estable (documentarlo en el módulo):

| Sitio | Patrón típico |
|-------|----------------|
| La Nación | Sufijo `-nidDDMMYYYY` en el path |
| Infobae | `/tema/YYYY/MM/DD/` en el path |
| Clarín | `article:published_time` en el HTML vs partición UTC |

Implementar `collect_*_urls_for_day(html, partition_day)` con regex sobre `href`, deduplicar, cap con env (`MAX_LINKS_PER_SECTION`).

### Extraer campos por artículo

| Campo | Origen HTML |
|-------|-------------|
| `titulo` | `og:title` o primer `h1` |
| `fecha_publicacion` | `article:published_time` o `<time datetime>`; fallback = medianoche UTC del día de partición |
| `cuerpo_md` | Párrafos dentro de `article` / cuerpo; unir con `\n\n`, filtrar textos muy cortos |
| `url` | URL canónica del GET |
| `tema` | Sección lógica (política, opinión, etc.) según hub de origen |

### Landing markdown (frontmatter)

Plantilla mínima (escapar `"` en títulos):

```markdown
---
tema: "politica"
title: "Título de la nota"
url: https://ejemplo.com/...
fecha_publicacion: 2026-04-19T00:10:00+00:00
scraped_at: 2026-04-19T12:00:00+00:00
landing_key: landing/<fuente>/politica/2026/04/19/slug.md
---

Cuerpo en texto plano o párrafos...
```

Clave MinIO: `landing/<fuente>/<tema>/YYYY/MM/DD/<slug>.md`.

**`lib.py` puede** usar `from __future__ import annotations` (no hay `@asset` ni inyección de recursos).

---

## 2. Dagster assets (bronze)

### Estructura de archivos

```text
assets/bronze/<fuente>/
  __init__.py          # exporta assets + LAN_*_DAILY si aplica
  lib.py               # scrape + build_markdown_file
  assets.py            # landing + bronze (o opinion_assets.py si hay 2 tablas)
jobs/<fuente>_job.py   # define_asset_job con ambos assets
```

Registrar el paquete en `datasyn/definitions.py` → `load_assets_from_modules([..., bronze_<fuente>])`. El job se descubre solo vía `collect_named(jobs)`.

### Particiones

`DailyPartitionsDefinition(start_date=..., end_offset=1)` — una partición = un día calendario de **publicación** (no día de scrape).

### Dos assets

1. **`<fuente>_landing_markdown`** — `scrape_*_for_partition(partition_day)` → `put_object` MinIO.
2. **`<fuente>_noticias_bronze`** — `deps=[landing]`, lista objetos con segmento `/YYYY/MM/DD/`, parsea frontmatter, escribe DuckDB.

### Esquema bronze con metadatos (tabla de artículos)

Nombres en **snake_case**, schema **`bronze`**:

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

- **`tema`**: sección / rubro.
- **`titulo`**, **`url`**: identidad editorial.
- **`cuerpo_md`**: texto para análisis downstream.
- **`fecha_publicacion`**, **`scraped_at`**: linaje temporal.
- **`landing_key`**: trazabilidad al objeto MinIO.

Variante **dos tablas** (ej. opinión): `bronze.<fuente>_opinion_columnistas` (`columnista_id`, `nombre`, `autor_url`, `slug`, `perfil_politico`, `scraped_at`, `landing_key`) y `bronze.<fuente>_opinion_notas` con **`columnista_id`** FK lógica hacia columnistas.

Idempotencia por día:

```sql
DELETE FROM bronze.<fuente>_noticias
WHERE CAST(fecha_publicacion AS DATE) = DATE '<partition_key>';
-- luego INSERT filas del landing de ese día
```

### CRÍTICO — `from __future__ import annotations`

| Archivo | ¿Usar `from __future__ import annotations`? |
|---------|---------------------------------------------|
| `lib.py`, utilidades scrape | **Sí** (opcional) |
| **`assets.py`** con `@asset` y **`database: DuckDBResource`** | **NO** |

Con `from __future__ import annotations`, las anotaciones quedan como strings y **Dagster puede fallar** al resolver `DuckDBResource` para el recurso `database`.

Los `assets.py` de referencia (`infobae/assets.py`, `lanacion/assets.py`, `clarin/assets.py`) **no** importan ese future.

### Docker Compose (build)

Si dos servicios comparten la **misma** `image:` (ej. `dagster-runtime`), solo **uno** debe tener `build:`. El otro solo `image:` — evita BuildKit `image "...": already exists` en `make images-build`.

---

## 3. Job Dagster

```python
define_asset_job(
    name="<fuente>_backfill_job",
    selection=AssetSelection.assets(landing_asset, bronze_asset),
    partitions_def=..._DAILY,
    description="Scrape → MinIO → bronze.<fuente>_noticias",
)
```

Materializar en UI: elegir rango de particiones → Launchpad.

---

## 4. Ingesta vía agente (DuckDB MCP, sin Dagster)

Solo para pruebas o cargas puntuales:

1. Confirmar landing bajo `/data-local/...` o listar MinIO con `storage_*` / `duckdb_list_data_mount`.
2. **`duckdb_get_schema`** antes de asumir nombres.
3. **`CREATE SCHEMA IF NOT EXISTS bronze`**.
4. Una sentencia por `duckdb_execute_query` (sin `;` encadenado).
5. Validar: `SELECT COUNT(*)`, `SELECT titulo, url, fecha_publicacion FROM bronze.<tabla> ORDER BY fecha_publicacion DESC LIMIT 5`.

No inventar paths tipo `/inbox/` — solo `/data-local/...`.

---

## 5. Metadatos en catálogo (opcional)

Si existe catálogo Postgres (`dagster_catalog_*`):

- Después de crear la tabla, registrar dataset con descripción, columnas, tags (`medio`, `bronze`, `scrape`), owner y `source_url` del hub.
- Seguir `./skills/update-catalog/SKILL.md` y `./skills/catalog-sql/SKILL.md` cuando estén en el repo.

En la tabla bronze, los campos listados arriba **son** el mínimo de metadatos operativos; el catálogo añade descubrimiento para el agente.

---

## 6. Checklist de cierre

- [ ] Hub y patrón de fecha documentados en docstring del `lib.py`
- [ ] Frontmatter con `url`, `fecha_publicacion`, `scraped_at`, `landing_key`
- [ ] Tabla `bronze.<nombre>` creada con columnas de metadatos
- [ ] `assets.py` **sin** `from __future__ import annotations`
- [ ] Job + exports en `__init__.py` + `definitions.py`
- [ ] `SELECT COUNT(*)` y muestra de 3 filas tras materializar una partición
- [ ] Rate limit / caps por env documentados

---

## Ejemplo de consulta

```sql
SELECT tema, titulo, url, CAST(fecha_publicacion AS DATE) AS dia
FROM bronze.lanacion_noticias
WHERE CAST(fecha_publicacion AS DATE) = DATE '2026-04-19'
ORDER BY fecha_publicacion DESC
LIMIT 10;
```

---

## Anti-patrones

- Scrape directo a bronze sin landing (pierdes reproceso y auditoría).
- `CREATE TABLE ... AS SELECT` sin `LIMIT 0` en tablas que ya existen (filas stale).
- Placeholder URLs en SQL ejecutable.
- Duplicar `build:` en compose para la misma imagen.
- `from __future__ import annotations` en módulos `@asset` con `DuckDBResource`.
