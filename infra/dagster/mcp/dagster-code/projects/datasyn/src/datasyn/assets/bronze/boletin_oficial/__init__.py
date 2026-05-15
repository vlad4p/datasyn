"""Export Boletín Oficial (tercera / contrataciones) bronze assets."""

from datasyn.assets.bronze.boletin_oficial.assets import (
    BOA_TERCERA_DAILY,
    boa_tercera_contrataciones_bronze,
    boa_tercera_contrataciones_landing,
)

__all__ = [
    "BOA_TERCERA_DAILY",
    "boa_tercera_contrataciones_landing",
    "boa_tercera_contrataciones_bronze",
]
