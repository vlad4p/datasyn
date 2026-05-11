"""{description}"""

from dagster import define_asset_job, AssetSelection


{name} = define_asset_job(
    name="{name}",
    selection=AssetSelection.{selection_expr},
    description={description_lit},
)
