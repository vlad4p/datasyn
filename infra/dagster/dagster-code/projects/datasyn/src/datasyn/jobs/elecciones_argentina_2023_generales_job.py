"""Job: landing ZIP elecciones 2023 + carga bronze del CSV de resultados."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.elecciones_argentina import (
    elecciones_argentina_2023_generales_landing,
    resultado_electorales_2023_generales,
)

elecciones_argentina_2023_generales_job = define_asset_job(
    name="elecciones_argentina_2023_generales_job",
    selection=AssetSelection.assets(
        elecciones_argentina_2023_generales_landing,
        resultado_electorales_2023_generales,
    ),
    description=(
        "Descarga 2023_generales_1.zip a MinIO, descomprime en "
        "landing/elecciones_argentina/2023_generales_1/ y carga "
        "bronze.resultado_electorales_2023_generales."
    ),
)
