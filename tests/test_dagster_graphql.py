"""Dagster GraphQL helpers (run: uv run pytest tests/test_dagster_graphql.py)."""

from agent.utils.dagster_graphql import infer_duckdb_fqn


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
