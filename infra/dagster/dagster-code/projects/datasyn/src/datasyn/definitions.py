"""Dagster `Definitions` entry point.

Most bronze modules are loaded with ``load_assets_from_modules``. Los CSV UCA
(``uca_csv``) se agregan explícitamente (``uca_*`` + indicadores Censo 2022).
"""

from __future__ import annotations

import os

from dagster import Definitions, load_assets_from_modules
from dagster_duckdb import DuckDBResource

from .assets.bronze.indec_censo import indec_censo_2022_redatam as bronze_indec_censo_2022
from .assets.bronze.indec_censo import radios_censales as bronze_radios
from .assets.bronze.indec_censo.uca_csv import (
    indicadores_censo_2022_argentina,
    indicadores_censo_2022_argentina_geojson,
    uca_censo,
    uca_departamentos,
    uca_provincias,
)
from .assets.bronze import elecciones_argentina as bronze_elecciones
from .assets.bronze.indec_eph import indec_eph_trimestral as bronze_eph
from .assets.bronze.indec_eph import indec_eph_variables as bronze_eph_variables
from . import jobs, schedules, sensors
from .utils.collect import collect_named

resources = {
    "database": DuckDBResource(
        database=os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    ),
}

defs = Definitions(
    assets=[
        *load_assets_from_modules(
            [
                bronze_elecciones,
                bronze_eph,
                bronze_eph_variables,
                bronze_radios,
                bronze_indec_censo_2022,
            ]
        ),
        uca_censo,
        uca_departamentos,
        uca_provincias,
        indicadores_censo_2022_argentina,
        indicadores_censo_2022_argentina_geojson,
    ],
    jobs=collect_named(jobs),
    schedules=collect_named(schedules),
    sensors=collect_named(sensors),
    resources=resources,
)
