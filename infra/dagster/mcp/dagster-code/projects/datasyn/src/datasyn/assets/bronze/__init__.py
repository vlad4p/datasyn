"""Bronze-layer Dagster asset domains.

- ``indec_censo``: census geographies and UCA census CSVs.
- ``elecciones_argentina``: elecciones nacionales (landing ZIP/MinIO + tablas bronze).
- ``infobae``: noticias Infobae (política, judiciales, economía) → MinIO markdown + bronze.
- ``clarin``: noticias Clarín (política, economía, rural) → MinIO markdown + bronze.
- ``lanacion``: noticias La Nación + opinión/columnistas (landing + bronze).
- ``boletin_oficial``: Boletín Oficial tercera (contrataciones) → MinIO PDF/HTML + bronze.
- ``tn``: noticias TN (tecno, política, economía, opinión) → MinIO markdown + bronze.
- ``oecd_ai_incidents``: OECD AIM Argentina incidents → MinIO JSON + bronze.
"""
