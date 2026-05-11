"""PostgreSQL schema snapshot for catalog ``catalog_get_schema`` introspection."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("dagster-mcp")


def fetch_public_schema(conn: Any) -> dict[str, Any]:
    """Tables, columns, and FKs in ``public`` (Datacyber catalog tables)."""
    tables: dict[str, Any] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """
        )
        for row in cur.fetchall():
            tname = row["table_name"]
            tables.setdefault(tname, {"columns": []})
            tables[tname]["columns"].append(
                {
                    "name": row["column_name"],
                    "data_type": row["data_type"],
                    "nullable": (row["is_nullable"] or "").upper() == "YES",
                }
            )

        cur.execute(
            """
            SELECT
                tc.table_name AS from_table,
                kcu.column_name AS from_column,
                ccu.table_name AS to_table,
                ccu.column_name AS to_column,
                tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
            """
        )
        fks = []
        for row in cur.fetchall():
            fks.append(
                {
                    "from_table": row["from_table"],
                    "from_column": row["from_column"],
                    "to_table": row["to_table"],
                    "to_column": row["to_column"],
                    "constraint": row["constraint_name"],
                }
            )

    log.info("fetch_public_schema tables=%s fks=%s", len(tables), len(fks))
    return {"schema": "public", "tables": tables, "foreign_keys": fks}
