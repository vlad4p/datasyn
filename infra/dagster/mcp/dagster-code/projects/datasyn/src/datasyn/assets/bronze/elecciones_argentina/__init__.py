"""Bronze assets: datos electorales Argentina (landing MinIO + tablas DuckDB)."""

from .elecciones_2023_generales import (
    elecciones_argentina_2023_generales_landing,
    resultado_electorales_2023_generales,
)

__all__ = [
    "elecciones_argentina_2023_generales_landing",
    "resultado_electorales_2023_generales",
]
