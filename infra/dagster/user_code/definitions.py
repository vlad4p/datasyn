"""Empty Dagster code location for local infra development.

Production pipelines live in the sibling ``datasyn-code`` repo; build and tag that
image as ``dagster_user_code_image`` when you need real assets (see ``README.md``).
"""

from dagster import Definitions

defs = Definitions()
