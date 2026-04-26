"""{description}"""

from dagster import RunRequest, SkipReason, sensor

from ..jobs.{job} import {job}


@sensor(
    name="{name}",
    job={job},
    minimum_interval_seconds={minimum_interval_seconds},
    description={description_lit},
)
def {name}(context):
    """{description}

    Replace the body with logic that yields `RunRequest(run_key=..., run_config=...)`
    when work should be triggered, or `SkipReason("...")` when not.
    """
    yield SkipReason("sensor scaffolded but no trigger logic implemented yet")
