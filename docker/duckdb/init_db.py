"""Create the warehouse DuckDB file on the mounted volume (idempotent).

Bootstraps a **medallion** layout (schemas only; no tables except the marker):

- ``bronze`` — landing / source-aligned copies (files, extracts)
- ``silver`` — cleansed, conformed, testable models
- ``gold`` — curated marts and consumer-facing datasets

Re-running is safe: every step uses ``IF NOT EXISTS``.
"""

from __future__ import annotations

import os

import duckdb

path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb")
parent = os.path.dirname(path)
if parent:
    os.makedirs(parent, exist_ok=True)

_MEDALLION_SCHEMAS: tuple[str, ...] = (
    "bronze",
    "silver",
    "gold",
)

con = duckdb.connect(path)
try:
    for name in _MEDALLION_SCHEMAS:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")
    con.execute("CREATE TABLE IF NOT EXISTS _datacyber_init (ready INTEGER DEFAULT 1)")
finally:
    con.close()

print(f"DuckDB ready at {path} (schemas: {', '.join(_MEDALLION_SCHEMAS)})")
