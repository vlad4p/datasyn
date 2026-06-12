---
name: add-dagster-job
description: >-
  Add a Dagster asset job (define_asset_job) for existing assets in datasyn-code.
  Use when the user asks to create a job, backfill job, or group assets for
  Launchpad materialization without new asset code.
---

# Agregar un job Dagster

Playbook para crear **`define_asset_job`** sobre assets **ya existentes**. No requiere editar `definitions.py` para el job: `collect_named(jobs)` lo registra automáticamente.

Prompt listo para copiar: [`prompts/add-dagster-job.txt`](../../prompts/add-dagster-job.txt).

---

## Convención obligatoria

| Regla | Ejemplo |
|-------|---------|
| Archivo | `src/datasyn/jobs/<nombre>_job.py` |
| Símbolo exportado | `<nombre>_job` (mismo nombre que el archivo sin `.py`) |
| Nombre interno del job | `<nombre>_backfill_job` o `<nombre>_job` (string en `define_asset_job`) |

Referencias:

- Particionado: `src/datasyn/jobs/tn_job.py`, `infobae_job.py`
- Sin particiones: `src/datasyn/jobs/uca_censo_2022_job.py`

---

## Job particionado (scrape / daily)

```python
"""Job particionado: scrape <fuente> → bronze."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.<fuente>.assets import (
    FUENTE_DAILY,
    fuente_landing_markdown,
    fuente_noticias_bronze,
)

fuente_job = define_asset_job(
    name="fuente_backfill_job",
    selection=AssetSelection.assets(fuente_landing_markdown, fuente_noticias_bronze),
    partitions_def=FUENTE_DAILY,
    description="Backfill diario: landing → bronze.",
)
```

Reutilizar la **misma** `DailyPartitionsDefinition` que los assets.

---

## Job sin particiones (CSV / one-shot)

```python
from dagster import AssetSelection, define_asset_job

mi_fuente_job = define_asset_job(
    name="mi_fuente_job",
    selection=AssetSelection.assets("asset_a", "asset_b"),
    description="Materializa assets bronze de mi_fuente.",
)
```

---

## Schedule opcional

Si el usuario pide ejecución automática, crear schedule en `schedules/` — ver [`skills/add-dagster-schedule/SKILL.md`](../add-dagster-schedule/SKILL.md).

---

## Validación

```bash
make dev
```

Comprobar en la UI: **Jobs** → job visible → Launchpad con partición (si aplica).

---

## Anti-patrones

- Exportar el job con nombre distinto al archivo (`foo_job.py` exportando `bar_job`).
- `partitions_def` distinta a la de los assets particionados.
- Ops/graph jobs cuando un asset graph basta.
