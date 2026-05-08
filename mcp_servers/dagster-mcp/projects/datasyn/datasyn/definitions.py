"""Dagster `Definitions` entry point.

Assets live under ``assets/bronze``, ``assets/silver``, ``assets/gold``. Register
each module that defines ``@asset`` functions via ``load_assets_from_modules``.
Jobs / schedules / sensors keep the scaffold convention (filename matches symbol).
"""

from __future__ import annotations

import os

from dagster import Definitions, load_assets_from_modules
from dagster_duckdb import DuckDBResource

from .assets.bronze import indec_eph_trimestral as bronze_eph
from .assets.bronze import indec_eph_variables as bronze_eph_variables
from .assets.bronze import radios_censales as bronze_radios
from . import jobs, schedules, sensors
from ._collect import collect_named

resources = {
    "database": DuckDBResource(
        database=os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    ),
}

defs = Definitions(
    assets=load_assets_from_modules([bronze_eph, bronze_eph_variables, bronze_radios]),
    jobs=collect_named(jobs),
    schedules=collect_named(schedules),
    sensors=collect_named(sensors),
    resources=resources,
)
