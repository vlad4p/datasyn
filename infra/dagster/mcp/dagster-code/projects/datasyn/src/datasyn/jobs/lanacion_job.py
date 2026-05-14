"""Job particionado: scrape La Nación → landing MinIO → ``bronze.lanacion_noticias``."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.lanacion.assets import (
    LAN_DAILY,
    lanacion_landing_markdown,
    lanacion_noticias_bronze,
)

lanacion_job = define_asset_job(
    name="lanacion_backfill_job",
    selection=AssetSelection.assets(lanacion_landing_markdown, lanacion_noticias_bronze),
    partitions_def=LAN_DAILY,
    description=(
        "Backfill diario: (1) scrape La Nación (política, economía, editoriales, Buenos Aires; "
        "judiciales vía hub seguridad) y guarda markdown en MinIO bajo ``landing/lanacion/``; "
        "(2) ingesta a ``bronze.lanacion_noticias`` (Iceberg si ``ICEBERG_REST_ENDPOINT``). "
        "Elegir rango de particiones en el Launchpad."
    ),
)
