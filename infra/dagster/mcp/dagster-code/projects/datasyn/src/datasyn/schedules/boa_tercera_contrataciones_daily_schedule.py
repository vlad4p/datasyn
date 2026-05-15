"""Ejecuta ``boa_tercera_contrataciones_job`` diariamente (14:00 UTC) para la partición del día."""

from dagster import DefaultScheduleStatus, build_schedule_from_partitioned_job

from datasyn.jobs.boa_tercera_contrataciones_job import boa_tercera_contrataciones_job

boa_tercera_contrataciones_daily_schedule = build_schedule_from_partitioned_job(
    boa_tercera_contrataciones_job,
    name="boa_tercera_contrataciones_daily_schedule",
    hour_of_day=14,
    minute_of_hour=0,
    default_status=DefaultScheduleStatus.STOPPED,
)
