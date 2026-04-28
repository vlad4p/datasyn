"""Gold-layer assets."""

from dagster import load_assets_from_modules

GOLD_ASSETS = load_assets_from_modules([])

__all__ = ["GOLD_ASSETS"]
