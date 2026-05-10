"""Materializar solo ``radios_censales`` (MinIO → bronze.radios_censales)."""

from dagster import AssetSelection, define_asset_job

radios_censales_job = define_asset_job(
    name="radios_censales_job",
    selection=AssetSelection.assets("radios_censales"),
    description="Ingesta CSV desde MinIO (landing/radio_censal/radios-censales.csv) a bronze.radios_censales.",
)
