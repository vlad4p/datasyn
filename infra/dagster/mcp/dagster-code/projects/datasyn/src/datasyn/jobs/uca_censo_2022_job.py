"""Materializar ingestas UCA / indicadores Censo 2022 (MinIO → bronze)."""

from dagster import AssetSelection, define_asset_job

uca_censo_2022_job = define_asset_job(
    name="uca_censo_2022_job",
    selection=AssetSelection.assets(
        "uca_censo",
        "uca_departamentos",
        "uca_provincias",
        "indicadores_censo_2022_argentina",
        "indicadores_censo_2022_argentina_geojson",
    ),
    description=(
        "Ingesta CSV desde MinIO (prefijo landing/censo_2022/uca/ o UCA_LANDING_PREFIX) "
        "a bronze.uca_* e indicadores Censo 2022."
    ),
)
