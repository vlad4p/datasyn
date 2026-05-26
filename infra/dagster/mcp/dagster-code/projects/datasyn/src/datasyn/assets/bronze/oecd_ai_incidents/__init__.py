"""Export OECD AI incidents bronze assets."""

from datasyn.assets.bronze.oecd_ai_incidents.assets import (
    OECD_AI_INCIDENTS_DAILY,
    oecd_ai_incidents_bronze,
    oecd_ai_incidents_landing,
)

__all__ = [
    "OECD_AI_INCIDENTS_DAILY",
    "oecd_ai_incidents_landing",
    "oecd_ai_incidents_bronze",
]
