"""Dagster `Definitions` entry point — auto-collects every submodule under
`assets/`, `jobs/`, `schedules/`, `sensors/`. Each file picks the symbol whose
name matches the module name, so `jobs/example_job.py` must export
`example_job`.
"""

from __future__ import annotations

from dagster import Definitions, load_assets_from_package_module

from . import assets, jobs, schedules, sensors
from ._collect import collect_named


defs = Definitions(
    assets=load_assets_from_package_module(assets),
    jobs=collect_named(jobs),
    schedules=collect_named(schedules),
    sensors=collect_named(sensors),
)
