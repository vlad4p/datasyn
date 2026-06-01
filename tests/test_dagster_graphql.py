"""Tests for Dagster GraphQL helpers."""

from agent.config import dagster_graphql_url
from agent.utils.dagster_graphql import (
    infer_duckdb_fqn,
    metadata_lookup,
    parse_metadata_entries,
)


def test_dagster_graphql_url_from_base() -> None:
    assert dagster_graphql_url(base_url="http://192.0.2.10:3001") == "http://192.0.2.10:3001/graphql"


def test_infer_fqn_from_tags() -> None:
    fqn = infer_duckdb_fqn(
        ["bronze", "infobae"],
        {"fully_qualified_name": "bronze.noticias_politica"},
        {},
    )
    assert fqn == "bronze.noticias_politica"


def test_infer_fqn_from_path() -> None:
    fqn = infer_duckdb_fqn(["gold", "indec_eph_usu_hogar"], {}, {})
    assert fqn == "gold.indec_eph_usu_hogar"


def test_infer_fqn_from_materialization_metadata() -> None:
    fqn = infer_duckdb_fqn(
        ["boa_tercera_contrataciones_bronze"],
        {},
        {"fqn": "bronze.boa_tercera_contrataciones_avisos"},
    )
    assert fqn == "bronze.boa_tercera_contrataciones_avisos"


def test_parse_metadata_entries_mixed_types() -> None:
    rows = parse_metadata_entries(
        [
            {"label": "rows", "__typename": "IntMetadataEntry", "intValue": 58},
            {"label": "duckdb_path", "__typename": "TextMetadataEntry", "text": "/data/warehouse.duckdb"},
            {"label": "enabled", "__typename": "BoolMetadataEntry", "boolValue": True},
            {"label": "payload", "__typename": "JsonMetadataEntry", "jsonString": "{\"a\":1}"},
        ]
    )
    assert len(rows) == 4
    lookup = metadata_lookup(
        [
            {"label": "fqn", "__typename": "TextMetadataEntry", "text": "bronze.table_a"},
        ]
    )
    assert lookup["fqn"] == "bronze.table_a"
