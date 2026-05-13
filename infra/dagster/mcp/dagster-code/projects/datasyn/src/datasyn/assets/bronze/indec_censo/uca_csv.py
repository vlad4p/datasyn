"""Bronze: CSV UCA desde MinIO → DuckDB nativo o Iceberg REST.

- Tablas ``uca_*`` clásicas: ``landing/indec/censo/uca/<archivo>.csv`` (histórico /
  ``scripts/r/upload_uca_to_minio.sh``).
- Indicadores Censo 2022 (hogares por radio): ``landing/censo_2022/uca/<archivo>.csv``
  → ``bronze.indicadores_censo_2022_argentina`` y ``bronze.indicadores_censo_2022_argentina_geojson``.

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

LANDING_PREFIX = (os.environ.get("UCA_LANDING_PREFIX") or "landing/indec/censo/uca").strip().strip(
    "/"
)
# Objetos subidos bajo ``landing/censo_2022/uca/`` (MinIO bucket típico ``data-local``).
UCA_CENSO_2022_LANDING_PREFIX = (
    os.environ.get("UCA_CENSO_2022_LANDING_PREFIX") or "landing/censo_2022/uca"
).strip().strip("/")
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
            UCA_CENSO_2022_LANDING_PREFIX,
            "Indicadores_de_hogares_radios_2022_argentina.csv",
        ),
        local_override_env=_LOCAL_ENV,
        local_filename="Indicadores_de_hogares_radios_2022_argentina.csv",
    ),
    BronzeMinioDuckdbSpec(
        asset_name="indicadores_censo_2022_argentina_geojson",
        object_key=_key(UCA_CENSO_2022_LANDING_PREFIX, UCA_FILE_INDICADORES_GEOJSON_ARGENTINA),
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
    "UCA_FILE_INDICADORES_GEOJSON_ARGENTINA",
    "indicadores_censo_2022_argentina",
    "indicadores_censo_2022_argentina_geojson",
    "uca_censo",
    "uca_departamentos",
    "uca_provincias",
]
