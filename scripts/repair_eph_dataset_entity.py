#!/usr/bin/env python3
"""Repair INDEC EPH gold tables in dataset_entity: columns from DuckDB + governance envelope.

Rebuilds `entity_json` for the two fixed INDEC EPH gold FQNs with: full `columns` array
introspected from DuckDB, OpenData-style tags, `customProperties.ingestHistory` with one
entry per loaded (year, quarter) slice (auto-detected from `ANO4` / `TRIMESTRE` in the
warehouse), and `tag_usage` refresh.

Run (from repo root; auto-detects Q1/Q2/Q3/Q4 slices present in DuckDB):

  uv run --with duckdb --with 'psycopg[binary]' scripts/repair_eph_dataset_entity.py \\
    --duckdb /path/to/warehouse.duckdb \\
    --database-url postgresql://datacyber:datacyber@127.0.0.1:5433/datacyber_catalog

Optional flags: `--hogar-txt` / `--individual-txt` (repeatable) override or add logical
`/data-local/...` paths in ingestHistory; `--metadata-json` (repeatable) enriches entries
with `pageUrl` / `sourceSha256` / `fetchedAtUtc` by matching `year` + `quarter`.

Optional: mount Docker volume read-only, e.g. ``-v datacyber-mcp_duckdb_data:/duck:ro`` and
``--duckdb /duck/warehouse.duckdb``. Use ``host.docker.internal`` instead of ``127.0.0.1``
when the script runs inside a container.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PAGE_URL = "https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos-1"
_TQY_RE = re.compile(r"T([1-4])(\d{2})\.txt$", re.IGNORECASE)


def _columns_json(con: Any, table: str) -> list[dict[str, str]]:
    q = """
    WITH ordered AS (
      SELECT column_name, data_type
      FROM information_schema.columns
      WHERE table_schema = 'gold' AND table_name = ?
      ORDER BY ordinal_position
    )
    SELECT json_group_array(
      json_object('name', column_name, 'dataType', data_type, 'description', '')
    ) AS j
    FROM ordered
    """
    row = con.execute(q, [table]).fetchone()
    if not row or row[0] is None:
        raise RuntimeError(f"No columns found for gold.{table}")
    return json.loads(row[0])


def _slice_counts(con: Any, table: str) -> list[tuple[int, int, int]]:
    """Return [(year, quarter, row_count)] sorted, from live gold.{table}."""
    rows = con.execute(
        f"SELECT ANO4, TRIMESTRE, COUNT(*) FROM gold.{table} GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    return [(int(y), int(q), int(n)) for y, q, n in rows]


def _parse_year_quarter_from_path(path: str) -> tuple[int, int] | None:
    """Parse (year, quarter) from '.../usu_<role>_T<q><yy>.txt' (yy is 20yy)."""
    m = _TQY_RE.search(path)
    if not m:
        return None
    quarter = int(m.group(1))
    yy = int(m.group(2))
    return (2000 + yy, quarter)


def _load_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _hist_entry(
    *,
    year: int,
    quarter: int,
    row_count: int,
    data_local_txt_path: str | None,
    metadata_json_path: str | None,
    meta: dict[str, Any],
    now_iso: str,
) -> dict[str, Any]:
    page_url = str(meta.get("page_url", DEFAULT_PAGE_URL))
    entry: dict[str, Any] = {
        "year": year,
        "quarter": quarter,
        "quarterLabel": f"Q{quarter}",
        "ingestedAtUtc": now_iso,
        "rowCount": row_count,
        "pageUrl": page_url,
    }
    if data_local_txt_path:
        entry["dataLocalTxtPath"] = data_local_txt_path
    if metadata_json_path:
        entry["metadataJsonPath"] = metadata_json_path
    sha = meta.get("file", {}).get("sha256") if isinstance(meta.get("file"), dict) else None
    if sha:
        entry["sourceSha256"] = sha
    if meta.get("fetched_at_utc"):
        entry["fetchedAtUtc"] = str(meta["fetched_at_utc"])
    return entry


def _build_history(
    *,
    slices: list[tuple[int, int, int]],
    path_index: dict[tuple[int, int], str],
    meta_index: dict[tuple[int, int], dict[str, Any]],
    default_meta_path_fmt: str,
    now_iso: str,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for year, quarter, row_count in slices:
        key = (year, quarter)
        meta = meta_index.get(key, {})
        meta_json_path = (
            f"/data-local/indec/mercado_laboral/EPH/{year}/Q{quarter}/metadata.json"
            if default_meta_path_fmt
            else None
        )
        history.append(
            _hist_entry(
                year=year,
                quarter=quarter,
                row_count=row_count,
                data_local_txt_path=path_index.get(key),
                metadata_json_path=meta_json_path,
                meta=meta,
                now_iso=now_iso,
            )
        )
    return history


def _entity_doc(
    *,
    fqn: str,
    table: str,
    display: str,
    description: str,
    columns: list[dict[str, str]],
    history: list[dict[str, Any]],
    last_meta_path: str | None,
    created_at: str,
    updated_at: str,
) -> dict[str, Any]:
    return {
        "fullyQualifiedName": fqn,
        "name": table,
        "displayName": display,
        "description": description,
        "tableType": "Regular",
        "service": {"name": "duckdb-warehouse", "type": "DatabaseService"},
        "database": {"name": "main"},
        "schema": {"name": "gold"},
        "columns": columns,
        "tags": [
            {"tagFQN": "Source.INDEC", "source": 0},
            {"tagFQN": "Survey.EPH", "source": 0},
            {"tagFQN": "Theme.LaborMarket", "source": 0},
        ],
        "owners": [],
        "glossaryTerms": [],
        "upstreamLineage": [],
        "downstreamLineage": [],
        "sourceUrl": DEFAULT_PAGE_URL,
        "customProperties": {
            "domain": "mercado_laboral",
            "domainDisplayName": "Mercado laboral — Argentina",
            "dataProduct": "INDEC EPH microdatos usuarios",
            "publisher": "INDEC",
            "license": DEFAULT_PAGE_URL,
            "accessRights": "public",
            "temporalResolution": "quarterly",
            "ingestHistory": history,
            "lastMetadataJsonPath": last_meta_path,
        },
        "createdAt": created_at,
        "updatedAt": updated_at,
    }


def _path_index_from_args(paths: list[str]) -> dict[tuple[int, int], str]:
    idx: dict[tuple[int, int], str] = {}
    for raw in paths:
        yq = _parse_year_quarter_from_path(raw)
        if not yq:
            print(f"warning: could not parse year/quarter from '{raw}' (expected .../usu_*_T<q><yy>.txt); skipping path", file=sys.stderr)
            continue
        idx[yq] = raw
    return idx


def _meta_index(paths: list[Path]) -> dict[tuple[int, int], dict[str, Any]]:
    idx: dict[tuple[int, int], dict[str, Any]] = {}
    for p in paths:
        meta = _load_meta(p)
        if not meta:
            continue
        try:
            key = (int(meta.get("year")), int(meta.get("quarter")))
        except (TypeError, ValueError):
            print(f"warning: metadata.json at {p} missing year/quarter; skipping", file=sys.stderr)
            continue
        idx[key] = meta
    return idx


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--duckdb", required=True, help="Path to warehouse.duckdb (file-backed)")
    p.add_argument(
        "--database-url",
        required=True,
        help="PostgreSQL URL for datacyber_catalog (e.g. postgresql://datacyber:datacyber@127.0.0.1:5433/datacyber_catalog)",
    )
    p.add_argument(
        "--metadata-json",
        type=Path,
        action="append",
        default=[],
        help="Host path to a quarter metadata.json (repeatable). Matched to slices by year+quarter.",
    )
    p.add_argument(
        "--hogar-txt",
        action="append",
        default=[],
        help="Logical /data-local path for a usu_hogar_*.txt (repeatable). Year/quarter parsed from filename.",
    )
    p.add_argument(
        "--individual-txt",
        action="append",
        default=[],
        help="Logical /data-local path for a usu_individual_*.txt (repeatable). Year/quarter parsed from filename.",
    )
    args = p.parse_args()

    try:
        import duckdb
        import psycopg
    except ImportError:
        print("Install: uv run --with duckdb --with 'psycopg[binary]' scripts/repair_eph_dataset_entity.py ...", file=sys.stderr)
        return 1

    meta_index = _meta_index(list(args.metadata_json))
    hogar_paths = _path_index_from_args(list(args.hogar_txt))
    ind_paths = _path_index_from_args(list(args.individual_txt))

    con = duckdb.connect(args.duckdb, read_only=True)
    try:
        hogar_cols = _columns_json(con, "indec_eph_usu_hogar")
        ind_cols = _columns_json(con, "indec_eph_usu_individual")
        hogar_slices = _slice_counts(con, "indec_eph_usu_hogar")
        ind_slices = _slice_counts(con, "indec_eph_usu_individual")
    finally:
        con.close()

    if not hogar_slices or not ind_slices:
        print("error: no (ANO4, TRIMESTRE) slices found in DuckDB gold tables", file=sys.stderr)
        return 2

    now_iso = datetime.now(timezone.utc).isoformat()
    hogar_history = _build_history(
        slices=hogar_slices,
        path_index=hogar_paths,
        meta_index=meta_index,
        default_meta_path_fmt="",
        now_iso=now_iso,
    )
    ind_history = _build_history(
        slices=ind_slices,
        path_index=ind_paths,
        meta_index=meta_index,
        default_meta_path_fmt="",
        now_iso=now_iso,
    )
    # For lastMetadataJsonPath pick the latest slice's metadata.json if known, else None.
    last_y, last_q, _ = hogar_slices[-1]
    last_meta_path = (
        f"/data-local/indec/mercado_laboral/EPH/{last_y}/Q{last_q}/metadata.json"
        if meta_index or hogar_paths or ind_paths
        else None
    )

    hogar_fqn = "duckdb-warehouse.main.gold.indec_eph_usu_hogar"
    ind_fqn = "duckdb-warehouse.main.gold.indec_eph_usu_individual"

    hogar_doc = _entity_doc(
        fqn=hogar_fqn,
        table="indec_eph_usu_hogar",
        display="INDEC EPH — usu hogar (gold)",
        description=(
            "INDEC Encuesta Permanente de Hogares (EPH), nivel hogar, microdatos usuarios. "
            "Período de referencia en filas: ANO4, TRIMESTRE. Fuente: INDEC."
        ),
        columns=hogar_cols,
        history=hogar_history,
        last_meta_path=last_meta_path,
        created_at=now_iso,
        updated_at=now_iso,
    )
    ind_doc = _entity_doc(
        fqn=ind_fqn,
        table="indec_eph_usu_individual",
        display="INDEC EPH — usu individual (gold)",
        description=(
            "INDEC Encuesta Permanente de Hogares (EPH), nivel persona, microdatos usuarios. "
            "Período de referencia en filas: ANO4, TRIMESTRE. Fuente: INDEC."
        ),
        columns=ind_cols,
        history=ind_history,
        last_meta_path=last_meta_path,
        created_at=now_iso,
        updated_at=now_iso,
    )

    upsert_sql = """
    INSERT INTO dataset_entity (fully_qualified_name, entity_json)
    VALUES (%s, %s::jsonb)
    ON CONFLICT (fully_qualified_name)
    DO UPDATE SET entity_json = EXCLUDED.entity_json
    RETURNING id
    """

    with psycopg.connect(args.database_url, autocommit=True) as pg:
        with pg.cursor() as cur:
            for fqn, doc in ((hogar_fqn, hogar_doc), (ind_fqn, ind_doc)):
                cur.execute(upsert_sql, (fqn, json.dumps(doc)))
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(f"UPSERT returned no id for {fqn}")
                ds_id = int(row[0])
                cur.execute("DELETE FROM tag_usage WHERE target_id = %s", (ds_id,))
                for tag in doc.get("tags") or []:
                    cur.execute(
                        "INSERT INTO tag_usage (target_id, tag_fqn, source) VALUES (%s, %s, %s) "
                        "ON CONFLICT (target_id, tag_fqn) DO NOTHING",
                        (ds_id, tag["tagFQN"], int(tag.get("source", 0))),
                    )
                print(
                    f"OK {fqn} id={ds_id} columns={len(doc['columns'])} "
                    f"tags={len(doc.get('tags') or [])} history={len(doc['customProperties']['ingestHistory'])}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
