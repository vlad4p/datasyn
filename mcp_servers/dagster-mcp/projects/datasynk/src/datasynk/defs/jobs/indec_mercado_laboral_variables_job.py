"""Bronze→silver chain for the EPH variable register.

``variables_eph`` rasterizes the PDF and calls LiteLLM vision to populate
``bronze.indec_mercado_laboral_variables``; ``silver_indec_mercado_laboral_variables``
explodes the JSON array column into ``silver.indec_mercado_laboral_variables``.
"""

from __future__ import annotations

from dagster import AssetSelection, define_asset_job

indec_mercado_laboral_variables_job = define_asset_job(
    name="indec_mercado_laboral_variables_job",
    selection=AssetSelection.keys(
        "variables_eph",
        "silver_indec_mercado_laboral_variables",
    ),
    description=(
        "Bronze→silver chain for the EPH variable register: rasterize PDF + "
        "LiteLLM vision → bronze.indec_mercado_laboral_variables, then explode "
        "JSON array → silver.indec_mercado_laboral_variables."
    ),
)
