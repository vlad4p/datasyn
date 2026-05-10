"""{description}"""

from dagster import ScheduleDefinition

from ..jobs.{job} import {job}


{name} = ScheduleDefinition(
    name="{name}",
    job={job},
    cron_schedule="{cron}",
    description={description_lit},
)
