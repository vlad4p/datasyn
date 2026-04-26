"""{description}"""

from dagster import asset


@asset(group_name="{group}")
def {name}():
    """{description}"""
    return {{"asset": "{name}"}}
