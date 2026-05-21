"""Job particionado: scrape TN (tecno, política, economía, opinión) → ``bronze.tn_noticias``."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.tn.assets import TN_DAILY, tn_landing_markdown, tn_noticias_bronze

tn_job = define_asset_job(
    name="tn_backfill_job",
    selection=AssetSelection.assets(tn_landing_markdown, tn_noticias_bronze),
    partitions_def=TN_DAILY,
    description=(
        "Backfill diario: (1) scrape TN tecno/política/economía/opinión y guarda markdown "
        "en MinIO bajo ``landing/tn/``; (2) ingesta a ``bronze.tn_noticias`` "
        "(Iceberg si ``ICEBERG_REST_ENDPOINT``). Elegir rango de particiones en el Launchpad."
    ),
)
