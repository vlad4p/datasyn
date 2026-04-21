"""Create the warehouse DuckDB file on the mounted volume (idempotent)."""

from __future__ import annotations

import os

import duckdb

path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb")
parent = os.path.dirname(path)
if parent:
    os.makedirs(parent, exist_ok=True)

con = duckdb.connect(path)
con.execute("CREATE TABLE IF NOT EXISTS _datacyber_init (ready INTEGER DEFAULT 1)")
con.close()
print(f"DuckDB ready at {path}")
