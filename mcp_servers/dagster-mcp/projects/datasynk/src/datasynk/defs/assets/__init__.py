"""Aggregate medallion assets for the datasynk project."""

from .bronze import BRONZE_ASSETS
from .gold import GOLD_ASSETS
from .silver import SILVER_ASSETS

ALL_ASSETS = [*BRONZE_ASSETS, *SILVER_ASSETS, *GOLD_ASSETS]

__all__ = ["ALL_ASSETS", "BRONZE_ASSETS", "SILVER_ASSETS", "GOLD_ASSETS"]
