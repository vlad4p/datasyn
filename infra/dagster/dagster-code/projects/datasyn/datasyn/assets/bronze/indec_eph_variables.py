"""Bronze: INDEC EPH ``registro`` PDF — variables extracted via LiteLLM (Gemini 3.1 Flash Lite Preview).

Pipeline (single LiteLLM call, whole PDF inline):

1. Download ``EPH_registro_<Q>T<YEAR>.pdf`` and cache under
   ``DATA_LOCAL_ROOT/landing/indec/eph/variables/<year>/`` (synced to MinIO when configured).
2. Send the whole PDF (base64 ``application/pdf``) in **one** chat completion to the LiteLLM
   proxy with ``gemini/gemini-3.1-flash-lite-preview`` (override via ``INDEC_EPH_VARIABLES_LITELLM_MODEL``).
3. Parse the JSON response (``hogar``, ``individual``, ``anexo_summary``), iterate the variable
   arrays into ``VariableRow`` and ingest into ``bronze.indec_eph_variables`` (DuckDB native
   by default; Iceberg REST when ``ICEBERG_REST_ENDPOINT`` is set).
4. Surface the Spanish ``anexo_summary`` in materialization metadata.

Storage follows ``materialize_bronze_rows``: Iceberg REST when configured, else native DuckDB
``bronze.indec_eph_variables``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dagster import MaterializeResult, MetadataValue, asset
from dagster_duckdb import DuckDBResource

from datasyn.iceberg_bronze_lib import materialize_bronze_rows
from datasyn.indec_eph_variables_lib import (
    BRONZE_SCHEMA,
    SOURCE_PAGE,
    TABLE_VARIABLES,
    download_variables_pdf,
    sync_pdf_to_minio,
    variables_pdf_url,
)
from datasyn.indec_eph_variables_llm import DEFAULT_MODEL, extract_pdf_with_llm


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return int(raw)


_VARIABLES_SCHEMA_SQL = (
    "campo VARCHAR, tipo VARCHAR, longitud INTEGER, descripcion TEXT, "
    "registro_base VARCHAR, pagina INTEGER, year INTEGER, quarter INTEGER"
)
_VARIABLES_PLACEHOLDERS = "?, ?, ?, ?, ?, ?, ?, ?"


@asset(
    group_name="bronze",
    compute_kind="litellm",
    description=(
        "Download INDEC EPH ``registro`` PDF and send it whole, in a **single** LiteLLM chat "
        "completion (``gemini/gemini-3.1-flash-lite-preview`` by default), to extract every variable from "
        "both the ``hogar`` and ``individual`` registros plus a Spanish summary of the anexo. "
        "Writes ``bronze.indec_eph_variables`` (campo, tipo, longitud, descripcion, registro_base, "
        "pagina, year, quarter); the anexo summary is stored in materialization metadata."
    ),
)
def indec_eph_variables(context, database: DuckDBResource) -> MaterializeResult:
    year = _int_env("INDEC_EPH_TRIMESTRAL_YEAR", 2025)
    quarter = _int_env("INDEC_EPH_VARIABLES_QUARTER", 3)

    url = variables_pdf_url(year, quarter)
    model = (os.environ.get("INDEC_EPH_VARIABLES_LITELLM_MODEL") or DEFAULT_MODEL).strip()
    proxy_base = (
        os.environ.get("LITELLM_PROXY_BASE")
        or os.environ.get("LITELLM_API_BASE")
        or ""
    ).strip()
    context.log.info(
        "indec_eph_variables start year=%s quarter=%s model=%s proxy=%s url=%s",
        year,
        quarter,
        model,
        proxy_base or "(unset)",
        url,
    )

    dl = download_variables_pdf(
        year=year,
        quarter=quarter,
        overwrite=False,
        emit=context.log.info,
    )
    pdf_path = Path(dl["path"])
    sync_res = sync_pdf_to_minio(pdf_path, emit=context.log.info)

    extracted = extract_pdf_with_llm(
        pdf_path,
        year=year,
        quarter=quarter,
        emit=context.log.info,
    )
    hogar_rows = extracted["hogar"]
    indiv_rows = extracted["individual"]
    anexo_summary = extracted["anexo_summary"]
    rows = [r.as_tuple() for r in (*hogar_rows, *indiv_rows)]

    duck_path = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb").strip()
    with database.get_connection() as con:
        out = materialize_bronze_rows(
            con,
            iceberg_namespace=BRONZE_SCHEMA,
            iceberg_table=TABLE_VARIABLES,
            schema_sql=_VARIABLES_SCHEMA_SQL,
            rows=rows,
            insert_placeholders=_VARIABLES_PLACEHOLDERS,
        )

    context.log.info(
        "indec_eph_variables done hogar=%d individual=%d total=%d storage=%s "
        "anexo_chars=%d llm_elapsed_sec=%.2f response_chars=%d",
        len(hogar_rows),
        len(indiv_rows),
        len(rows),
        out.get("storage"),
        len(anexo_summary),
        float(extracted.get("elapsed_sec") or 0.0),
        int(extracted.get("response_chars") or 0),
    )

    rel = out.get("iceberg_fqn") or out.get("duckdb_fqn")
    return MaterializeResult(
        metadata={
            "source_portal": MetadataValue.url(SOURCE_PAGE),
            "source_pdf_url": MetadataValue.url(url),
            "pdf_path": dl["path"],
            "pdf_bytes": dl["bytes"],
            "minio_uploaded": int(sync_res.get("uploaded", 0)),
            "minio_skipped": bool(sync_res.get("skipped", False)),
            "duckdb_path": duck_path,
            "storage": out.get("storage"),
            "relation_fqn": rel,
            "row_count": out.get("row_count"),
            "hogar_rows": len(hogar_rows),
            "individual_rows": len(indiv_rows),
            "year": year,
            "quarter": quarter,
            "anexo_chars": len(anexo_summary),
            "anexo_summary_es": MetadataValue.md(anexo_summary or "_(empty)_"),
            "litellm_model": model,
            "litellm_proxy_base": proxy_base or "(unset)",
            "litellm_elapsed_sec": float(extracted.get("elapsed_sec") or 0.0),
            "litellm_response_chars": int(extracted.get("response_chars") or 0),
        }
    )
