"""Reusable pipeline building blocks (component-style specs).

These mirror the *declarative spec → Definitions* idea from Dagster Components
(https://docs.dagster.io/guides/build/components): small frozen dataclasses and
factories that emit assets/jobs without requiring the separate ``dg`` CLI in this
repository's Dagster pin.

Prefer adding new MinIO → DuckDB bronze loads via
:class:`~datasyn.components.bronze_object_storage_duckdb.BronzeMinioDuckdbSpec`
instead of copying boto3 + ``read_csv_auto`` boilerplate.
"""

from datasyn.components.bronze_object_storage_duckdb import (
    BronzeMinioDuckdbSpec,
    DEFAULT_BRONZE_SCHEMA,
    make_bronze_minio_duckdb_asset,
)

__all__ = [
    "BronzeMinioDuckdbSpec",
    "DEFAULT_BRONZE_SCHEMA",
    "make_bronze_minio_duckdb_asset",
]
