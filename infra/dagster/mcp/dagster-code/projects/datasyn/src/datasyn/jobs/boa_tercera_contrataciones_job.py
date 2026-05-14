"""Job particionado: Boletín Oficial tercera (contrataciones) → MinIO → ``bronze.boa_tercera_contrataciones_avisos``."""

from dagster import AssetSelection, define_asset_job

from datasyn.assets.bronze.boletin_oficial.assets import (
    BOA_TERCERA_DAILY,
    boa_tercera_contrataciones_bronze,
    boa_tercera_contrataciones_landing,
)

boa_tercera_contrataciones_job = define_asset_job(
    name="boa_tercera_contrataciones_job",
    selection=AssetSelection.assets(
        boa_tercera_contrataciones_landing,
        boa_tercera_contrataciones_bronze,
    ),
    partitions_def=BOA_TERCERA_DAILY,
    description=(
        "Tercera sección (contrataciones): (1) portada ``/seccion/tercera/YYYYMMDD``, rubros "
        "``SUMINISTROS - …`` vía ``h5.seccion-rubro``, PDF por aviso (POST ``/pdf/download_aviso``) "
        "y HTML de detalle en MinIO bajo ``landing/boa/tercera/contrataciones/``; (2) ingesta diaria "
        "a ``bronze.boa_tercera_contrataciones_avisos``. Variables: ``BOA_DOWNLOAD_SLEEP_S``, "
        "``BOA_SKIP_PDF=true`` solo manifest/HTML."
    ),
)
