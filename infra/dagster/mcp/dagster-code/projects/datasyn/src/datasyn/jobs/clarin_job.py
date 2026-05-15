"""Job particionado: scrape Clarín → landing MinIO → ``bronze.clarin_noticias``."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.clarin.assets import (
    CLARIN_DAILY,
    clarin_landing_markdown,
    clarin_noticias_bronze,
)

clarin_job = define_asset_job(
    name="clarin_backfill_job",
    selection=AssetSelection.assets(clarin_landing_markdown, clarin_noticias_bronze),
    partitions_def=CLARIN_DAILY,
    description=(
        "Backfill diario: (1) scrape Clarín (política, economía, rural) y guarda markdown "
        "en MinIO bajo ``landing/clarin/``; (2) ingesta a ``bronze.clarin_noticias`` "
        "(Iceberg si ``ICEBERG_REST_ENDPOINT``). Elegir rango de particiones en el Launchpad."
    ),
)
