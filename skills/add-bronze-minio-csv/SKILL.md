---
name: add-bronze-minio-csv
description: >-
  Add Dagster bronze assets that load CSV (or text) from MinIO into DuckDB using
  BronzeMinioDuckdbSpec. Use when ingesting files already in object storage,
  UCA-style CSV loads, landing/censo paths, or MinIO to bronze without scraping.
---

# Bronze MinIO → DuckDB (CSV)

Playbook para cargar **archivos ya presentes en MinIO** (típicamente CSV bajo `landing/...`) a tablas **`bronze.*`** con el componente declarativo del repo.

Referencia canónica: `src/datasyn/assets/bronze/indec_censo/uca_csv.py` + `src/datasyn/components/bronze_object_storage_duckdb.py`.

Prompt listo para copiar: [`prompts/add-bronze-minio-csv.txt`](../../prompts/add-bronze-minio-csv.txt).

---

## Cuándo usar esta skill

- CSV u otro archivo **ya subido** a MinIO (bucket `MINIO_BUCKET`, default `data-local`).
- Varias tablas desde el mismo prefijo (`landing/censo_2022/uca/...`).
- Override local en dev (`UCA_FILES_LOCAL_DIR` pattern).

**No** uses para scrape HTML — ver [`skills/ingest-scrape-news-bronze/SKILL.md`](../ingest-scrape-news-bronze/SKILL.md).

---

## Patrón de código

```python
from datasyn.components.bronze_object_storage_duckdb import (
    BronzeMinioDuckdbSpec,
    make_bronze_minio_duckdb_asset,
)

MY_SPECS: tuple[BronzeMinioDuckdbSpec, ...] = (
    BronzeMinioDuckdbSpec(
        asset_name="mi_tabla",
        object_key="landing/mi_fuente/mi_tabla.csv",
        local_override_env="MI_FILES_LOCAL_DIR",  # opcional
        local_filename="mi_tabla.csv",             # opcional
    ),
)

mi_tabla = make_bronze_minio_duckdb_asset(MY_SPECS[0])
```

Campos útiles en `BronzeMinioDuckdbSpec`:

| Campo | Uso |
|-------|-----|
| `asset_name` | Nombre del asset Dagster (= tabla bronze por defecto) |
| `object_key` | Clave en MinIO (sin bucket) |
| `schema_name` | Default `bronze` |
| `table_name` | Default = `asset_name` |
| `local_override_env` + `local_filename` | Leer archivo local en dev sin MinIO |
| `read_csv_options` | Opciones DuckDB `read_csv_auto` |

---

## Registro

1. Crear módulo bajo `src/datasyn/assets/bronze/<fuente>/` (p. ej. `csv_assets.py`).
2. Exportar assets generados desde `__init__.py` si hace falta.
3. **`definitions.py`**:
   - Vía `load_assets_from_modules` si el módulo exporta assets estándar, **o**
   - Import explícito de cada asset (patrón UCA en `definitions.py`).
4. Job opcional: `jobs/<fuente>_job.py` con `AssetSelection.assets("asset_a", "asset_b", ...)`.

Los jobs se descubren solos con `collect_named(jobs)`.

---

## Job de ejemplo

Ver `src/datasyn/jobs/uca_censo_2022_job.py`:

```python
uca_censo_2022_job = define_asset_job(
    name="uca_censo_2022_job",
    selection=AssetSelection.assets(
        "uca_censo",
        "uca_departamentos",
    ),
    description="Ingesta CSV desde MinIO a bronze.*",
)
```

Archivo `uca_censo_2022_job.py` exporta símbolo `uca_censo_2022_job`.

---

## Variables de entorno

| Variable | Default | Uso |
|----------|---------|-----|
| `MINIO_BUCKET` | `data-local` | Bucket S3/MinIO |
| `DUCKDB_PATH` | `/data/warehouse.duckdb` | Warehouse |
| `ICEBERG_REST_ENDPOINT` | — | Publicación Iceberg opcional |

---

## Validación

```bash
make dev
```

Materializar assets desde la UI o Launchpad del job.

---

## Checklist

- [ ] `object_key` coincide con objeto real en MinIO
- [ ] Assets registrados en `definitions.py`
- [ ] Job creado si el usuario pidió materialización agrupada
- [ ] `make dev` sin errores
- [ ] Sin credenciales hardcodeadas
