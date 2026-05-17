"""Export La Nación bronze assets."""

from datasyn.assets.bronze.lanacion.assets import (
    LAN_DAILY,
    lanacion_landing_markdown,
    lanacion_noticias_bronze,
)
from datasyn.assets.bronze.lanacion.opinion_assets import (
    lanacion_opinion_bronze,
    lanacion_opinion_landing_markdown,
)

__all__ = [
    "LAN_DAILY",
    "lanacion_landing_markdown",
    "lanacion_noticias_bronze",
    "lanacion_opinion_bronze",
    "lanacion_opinion_landing_markdown",
]
