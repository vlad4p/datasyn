"""Silver-layer assets."""

from dagster import load_assets_from_modules

from . import silver_variables

SILVER_ASSETS = load_assets_from_modules([silver_variables])

__all__ = ["SILVER_ASSETS"]
