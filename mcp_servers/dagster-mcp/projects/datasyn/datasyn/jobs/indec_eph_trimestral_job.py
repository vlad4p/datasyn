"""Materialize INDEC EPH trimestral landing + DuckDB bronze tables."""

from dagster import AssetSelection, define_asset_job

indec_eph_trimestral_job = define_asset_job(
    name="indec_eph_trimestral_job",
    selection=AssetSelection.groups("bronze"),
    description="Download ZIPs/TXT, mirror to MinIO (optional), load bronze.indec_usu_* from TXT (Iceberg REST if ICEBERG_REST_ENDPOINT is set; else native DuckDB).",
)
