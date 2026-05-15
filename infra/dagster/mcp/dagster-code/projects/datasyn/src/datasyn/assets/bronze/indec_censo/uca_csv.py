"""Bronze: CSV UCA desde MinIO → DuckDB nativo o Iceberg REST.

- Todos los CSV UCA (tablas ``uca_*`` e indicadores Censo 2022): prefijo por defecto
  ``landing/censo_2022/uca/<archivo>.csv`` (bucket típico ``data-local``).
- Override: ``UCA_LANDING_PREFIX`` o ``UCA_CENSO_2022_LANDING_PREFIX`` (mismo valor si solo
  se define uno). Histórico ``landing/indec/censo/uca`` vía variable de entorno.

Las cargas siguen el patrón **component** declarativo
(:class:`~datasyn.components.bronze_object_storage_duckdb.BronzeMinioDuckdbSpec`);
ver https://docs.dagster.io/guides/build/components

``UCA_FILES_LOCAL_DIR`` + mismo nombre de archivo omite MinIO en desarrollo.
``read_csv_auto``: ``sample_size=-1``, ``all_varchar=true`` (igual que otros CSV bronze).
"""

from __future__ import annotations

import os

from datasyn.components.bronze_object_storage_duckdb import (
    BronzeMinioDuckdbSpec,
    make_bronze_minio_duckdb_asset,
)


def _uca_landing_prefix() -> str:
    for env_name in ("UCA_LANDING_PREFIX", "UCA_CENSO_2022_LANDING_PREFIX"):
        raw = os.environ.get(env_name)
        if raw and raw.strip():
            return raw.strip().strip("/")
    return "landing/censo_2022/uca"


# Un solo prefijo MinIO para ``censo.csv`` / ``departamentos.csv`` / ``provincias.csv`` e indicadores.
UCA_LANDING_PREFIX = _uca_landing_prefix()
# Alias retrocompatible con código que importaba ``UCA_CENSO_2022_LANDING_PREFIX``.
UCA_CENSO_2022_LANDING_PREFIX = UCA_LANDING_PREFIX
LANDING_PREFIX = UCA_LANDING_PREFIX
_LOCAL_ENV = "UCA_FILES_LOCAL_DIR"
# Objeto en MinIO suele ser ``…geojson….csv.csv``; sobreescribir si el bucket usa solo ``.csv``.
UCA_FILE_INDICADORES_GEOJSON_ARGENTINA = (
    os.environ.get("UCA_FILE_INDICADORES_GEOJSON_ARGENTINA")
    or "Indicadores_de_hogares_radios_2022_geojson_argentina.csv.csv"
).strip()


def _key(prefix: str, filename: str) -> str:
    return f"{prefix.strip().strip('/')}/{filename}".lstrip("/")


UCA_BRONZE_SPECS: tuple[BronzeMinioDuckdbSpec, ...] = (
    BronzeMinioDuckdbSpec(
        asset_name="uca_censo",
        object_key=_key(LANDING_PREFIX, "censo.csv"),
        local_override_env=_LOCAL_ENV,
        local_filename="censo.csv",
    ),
    BronzeMinioDuckdbSpec(
        asset_name="uca_departamentos",
        object_key=_key(LANDING_PREFIX, "departamentos.csv"),
        local_override_env=_LOCAL_ENV,
        local_filename="departamentos.csv",
    ),
    BronzeMinioDuckdbSpec(
        asset_name="uca_provincias",
        object_key=_key(LANDING_PREFIX, "provincias.csv"),
        local_override_env=_LOCAL_ENV,
        local_filename="provincias.csv",
    ),
    BronzeMinioDuckdbSpec(
        asset_name="indicadores_censo_2022_argentina",
        object_key=_key(
            UCA_LANDING_PREFIX,
            "Indicadores_de_hogares_radios_2022_argentina.csv",
        ),
        local_override_env=_LOCAL_ENV,
        local_filename="Indicadores_de_hogares_radios_2022_argentina.csv",
    ),
    BronzeMinioDuckdbSpec(
        asset_name="indicadores_censo_2022_argentina_geojson",
        object_key=_key(UCA_LANDING_PREFIX, UCA_FILE_INDICADORES_GEOJSON_ARGENTINA),
        local_override_env=_LOCAL_ENV,
        local_filename=UCA_FILE_INDICADORES_GEOJSON_ARGENTINA,
    ),
)

uca_censo = make_bronze_minio_duckdb_asset(UCA_BRONZE_SPECS[0])
uca_departamentos = make_bronze_minio_duckdb_asset(UCA_BRONZE_SPECS[1])
uca_provincias = make_bronze_minio_duckdb_asset(UCA_BRONZE_SPECS[2])
indicadores_censo_2022_argentina = make_bronze_minio_duckdb_asset(UCA_BRONZE_SPECS[3])
indicadores_censo_2022_argentina_geojson = make_bronze_minio_duckdb_asset(UCA_BRONZE_SPECS[4])

__all__ = [
    "UCA_BRONZE_SPECS",
    "UCA_CENSO_2022_LANDING_PREFIX",
    "UCA_LANDING_PREFIX",
    "LANDING_PREFIX",
    "UCA_FILE_INDICADORES_GEOJSON_ARGENTINA",
    "indicadores_censo_2022_argentina",
    "indicadores_censo_2022_argentina_geojson",
    "uca_censo",
    "uca_departamentos",
    "uca_provincias",
]
