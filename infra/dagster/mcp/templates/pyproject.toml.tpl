[project]
name = "{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.11"
dependencies = [
    "dagster>=1.9,<2",
    "dagster-webserver>=1.9,<2",
    "dagster-duckdb>=0.29,<0.30",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.dagster]
module_name = "{name}.definitions"
code_location_name = "{name}"

[tool.setuptools.packages.find]
include = ["{name}*"]
