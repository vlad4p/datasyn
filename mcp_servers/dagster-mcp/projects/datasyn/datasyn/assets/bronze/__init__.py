"""Bronze-layer Dagster assets (landing-aligned tables in schema ``bronze``).

- ``indec_eph_trimestral``: EPH ZIP/TXT landing, ``indec_usu_hogar``, ``indec_usu_individual``.
- ``indec_eph_variables``: registro PDF → LiteLLM extraction → ``indec_eph_variables``.
- ``radios_censales``: MinIO CSV → ``radios_censales``.
- ``indec_censo_2022_redatam``: Base_VP Redatam export CSV → ``indec_censo_2022_vp``.
- ``uca_csv``: UCA CSVs from MinIO → ``uca_*`` tables.
"""
