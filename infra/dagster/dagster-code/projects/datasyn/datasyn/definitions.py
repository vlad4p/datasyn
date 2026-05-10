"""Dagster `Definitions` entry point.

Most bronze modules are loaded with ``load_assets_from_modules``. UCA tables
(``uca_csv``) are appended explicitly so all five ``uca_*`` assets always appear
in the code location.
"""

from __future__ import annotations

import os

from dagster import Definitions, load_assets_from_modules
from dagster_duckdb import DuckDBResource

from .assets.bronze import indec_eph_trimestral as bronze_eph
from .assets.bronze import indec_eph_variables as bronze_eph_variables
from .assets.bronze import radios_censales as bronze_radios
from .assets.bronze import indec_censo_2022_redatam as bronze_indec_censo_2022
from .assets.bronze.uca_csv import (
    uca_censo,
    uca_departamentos,
    uca_indicadores_hogares_radios_2022_argentina,
    uca_indicadores_hogares_radios_2022_geojson_argentina,
    uca_provincias,
)
from . import jobs, schedules, sensors
from ._collect import collect_named

resources = {
    "database": DuckDBResource(
        database=os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    ),
}

defs = Definitions(
    assets=[
        *load_assets_from_modules(
            [
                bronze_eph,
                bronze_eph_variables,
                bronze_radios,
                bronze_indec_censo_2022,
            ]
        ),
        uca_censo,
        uca_departamentos,
        uca_provincias,
        uca_indicadores_hogares_radios_2022_argentina,
        uca_indicadores_hogares_radios_2022_geojson_argentina,
    ],
    jobs=collect_named(jobs),
    schedules=collect_named(schedules),
    sensors=collect_named(sensors),
    resources=resources,
)
