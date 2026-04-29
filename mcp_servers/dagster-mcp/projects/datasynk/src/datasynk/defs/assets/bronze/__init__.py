"""Bronze-layer assets."""

from dagster import load_assets_from_modules

from . import eph_year_usu, infobae_politica_fetch, variables_eph

BRONZE_ASSETS = load_assets_from_modules([eph_year_usu, infobae_politica_fetch, variables_eph])

__all__ = ["BRONZE_ASSETS"]
