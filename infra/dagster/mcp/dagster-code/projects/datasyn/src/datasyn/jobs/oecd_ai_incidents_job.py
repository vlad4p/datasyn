"""Job particionado: OECD AIM Argentina incidents → JSON landing → ``bronze.oecd_ai_incidents``."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.oecd_ai_incidents.assets import (
    OECD_AI_INCIDENTS_DAILY,
    oecd_ai_incidents_bronze,
    oecd_ai_incidents_landing,
)

oecd_ai_incidents_job = define_asset_job(
    name="oecd_ai_incidents_backfill_job",
    selection=AssetSelection.assets(oecd_ai_incidents_landing, oecd_ai_incidents_bronze),
    partitions_def=OECD_AI_INCIDENTS_DAILY,
    description=(
        "Backfill diario: (1) scrape OECD AIM incidents for Argentina on the selected date "
        "and stores one JSON per incident under ``landing/oecd_ai_incidents/`` in MinIO; "
        "(2) ingests the structured/raw JSON into ``bronze.oecd_ai_incidents`` "
        "(Iceberg if ``ICEBERG_REST_ENDPOINT``). Choose the incident date partition in Launchpad."
    ),
)
