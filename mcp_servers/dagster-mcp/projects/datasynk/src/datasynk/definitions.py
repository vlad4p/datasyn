"""Top-level :class:`~dagster.Definitions` for the ``datasynk`` code location."""

from __future__ import annotations

from pathlib import Path

from dagster import Definitions
from dotenv import load_dotenv

from .defs.assets import ALL_ASSETS
from .defs.jobs import indec_mercado_laboral_variables_job
from .defs.resources import resources

# Project root = directory that contains ``pyproject.toml`` and optional ``.env``.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.is_file():
    load_dotenv(_ENV_FILE, override=False)

defs = Definitions(
    assets=ALL_ASSETS,
    jobs=[indec_mercado_laboral_variables_job],
    resources=resources,
)
