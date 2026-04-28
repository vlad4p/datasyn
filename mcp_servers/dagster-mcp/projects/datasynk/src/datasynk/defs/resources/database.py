"""Shared DuckDB resource for datasynk assets."""

from __future__ import annotations

import os

from dagster_duckdb import DuckDBResource

database_resource = DuckDBResource(
    database=os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
)
