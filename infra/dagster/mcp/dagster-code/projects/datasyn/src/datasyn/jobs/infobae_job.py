"""Job particionado: scrape Infobae → landing MinIO → ``bronze.infobae_noticias``."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.infobae.assets import INF_DAILY, infobae_landing_markdown, infobae_noticias_bronze

infobae_job = define_asset_job(
    name="infobae_backfill_job",
    selection=AssetSelection.assets(infobae_landing_markdown, infobae_noticias_bronze),
    partitions_def=INF_DAILY,
    description=(
        "Backfill diario: (1) scrape Infobae política/judiciales/economía y guarda markdown "
        "en MinIO bajo ``landing/infobae/``; (2) ingesta a ``bronze.infobae_noticias`` "
        "(Iceberg si ``ICEBERG_REST_ENDPOINT``). Elegir rango de particiones en el Launchpad."
    ),
)
