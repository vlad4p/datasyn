"""Main Dagster :class:`~dagster.Definitions` for this code location.

Matches the scaffold in `Projects — Dagster project structure
<https://docs.dagster.io/dagster-basics-tutorial/projects#dagster-project-structure>`_.
"""

from __future__ import annotations

from dagster import Definitions

from .assets.eph_year_usu import build_eph_usu_assets

defs = Definitions(assets=build_eph_usu_assets())
