"""Job particionado: scrape La Nación Opinión / columnistas → MinIO → tablas bronze."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.lanacion.assets import LAN_DAILY
from datasyn.assets.bronze.lanacion.opinion_assets import (
    lanacion_opinion_bronze,
    lanacion_opinion_landing_markdown,
)

lanacion_opinion_job = define_asset_job(
    name="lanacion_opinion_backfill_job",
    selection=AssetSelection.assets(
        lanacion_opinion_landing_markdown,
        lanacion_opinion_bronze,
    ),
    partitions_def=LAN_DAILY,
    description=(
        "Backfill diario: (1) scrape columnistas y notas ``/opinion/...-nidDDMMYYYY`` del día; "
        "landing en ``landing/lanacion/opinion/``; (2) ingesta a "
        "``bronze.lanacion_opinion_columnistas`` (perfil político / biografía) y "
        "``bronze.lanacion_opinion_notas`` (``columnista_id``)."
    ),
)
