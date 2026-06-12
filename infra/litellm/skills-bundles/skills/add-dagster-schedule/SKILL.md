---
name: add-dagster-schedule
description: >-
  Add a Dagster schedule for a partitioned or non-partitioned job in datasyn-code.
  Use when the user asks for daily cron, automated runs, or build_schedule_from_partitioned_job.
---

# Agregar un schedule Dagster

Playbook para schedules en `src/datasyn/schedules/`. Auto-registro vía `collect_named(schedules)` — **no** editar `definitions.py`.

Prompt listo para copiar: [`prompts/add-dagster-schedule.txt`](../../prompts/add-dagster-schedule.txt).

Referencia: `src/datasyn/schedules/boa_tercera_contrataciones_daily_schedule.py`.

---

## Convención

| Regla | Ejemplo |
|-------|---------|
| Archivo | `schedules/<nombre>_schedule.py` |
| Símbolo | `<nombre>_schedule` |
| Estado default | `DefaultScheduleStatus.STOPPED` hasta activación explícita |

---

## Schedule para job particionado

```python
from dagster import DefaultScheduleStatus, build_schedule_from_partitioned_job

from datasyn.jobs.mi_fuente_job import mi_fuente_job

mi_fuente_daily_schedule = build_schedule_from_partitioned_job(
    mi_fuente_job,
    name="mi_fuente_daily_schedule",
    hour_of_day=14,
    minute_of_hour=0,
    default_status=DefaultScheduleStatus.STOPPED,
)
```

`build_schedule_from_partitioned_job` elige la partición del día según la política de Dagster.

---

## Validación

```bash
make dev
```

UI → **Schedules** → toggle ON solo cuando el operador lo decida.

---

## Checklist

- [ ] Import del job desde `datasyn.jobs.*`
- [ ] Nombre de archivo = símbolo exportado
- [ ] `DefaultScheduleStatus.STOPPED` por defecto
- [ ] `make dev` carga sin errores
