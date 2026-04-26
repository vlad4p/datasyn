---
name: scrape-indec-mercado-laboral
description: >-
  Scrape INDEC (Argentina) EPH labor-market microdatos in **TXT** format via
  `scrapper-mcp`: HEAD-probe candidates, download ZIPs into `/data-local/`,
  write `metadata.json`, then ingest with `duckdb_warehouse_query` and register
  with `catalog_*`. Use when the user says things like "Microdatos (2025)",
  "Microdatos y documentos 2016-2025", or explicitly asks to scrape INDEC EPH.
---

# Scrape INDEC EPH microdatos (TXT) via `scrapper_*`

`scrapper-mcp` is the **only component that writes under `/data-local/`**. The warehouse mounts the same directory **read-only**, so nothing else should download files during a chat turn.

Source: INDEC — [Institucional / Bases de Datos](https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos-1). The page is a JS-rendered SPA and is **not directly scrapeable** with plain HTTP. This scraper uses the **stable asset URL pattern** INDEC serves the same files from:

```
https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/EPH_usu_{Q}_Trim_{YEAR}_txt.zip
```

Supported range: **YEAR ≥ 2016**, **Q ∈ {1,2,3,4}** (post-rebuild EPH Continua). REDATAM and pre-2016 EPH are rejected by the scraper with a skipped entry + clear reason.

## Tools

| Tool (prefix `scrapper_`) | Purpose |
|---------------------------|---------|
| `scrapper_list_sources` | Static catalog: keys, page URLs, supported years, period examples, output layout. |
| `scrapper_indec_mercado_laboral_list` | HEAD-probe the period's candidates. **No download.** Returns JSON with `url`, `content_length`, `etag`, `last_modified`, `fqn_suggestion`, `exists`. |
| `scrapper_indec_mercado_laboral_download` | Download + unzip + write `metadata.json`. Params: `period` (str, required), `overwrite` (bool, default `False`), `unzip` (bool, default `True`). |

## Accepted `period` inputs

The scraper parses these forms (whitespace and trailing markers like `▾` are ignored):

- `Microdatos (2025)` — year 2025, Q1–Q4
- `Microdatos y documentos 2016-2025` — years 2016–2025, Q1–Q4 (**40 downloads** — confirm with user first)
- `Microdatos (2020-2021)` — years 2020–2021, Q1–Q4
- `Microdatos (2016-2019)` — years 2016–2019, Q1–Q4
- `2024` — year 2024, Q1–Q4
- `2025 Q3` / `2025 T3` / `2024 Q1,Q3` — specific quarters only

Pre-2016 (e.g. `Microdatos (2010-2014)`) and `Bases REDATAM (2010-2014)` are **rejected** by the scraper. Do not try to fetch those through this tool.

## Output layout

```
/data-local/indec/mercado_laboral/EPH/<YEAR>/Q<N>/
    EPH_usu_<N>_Trim_<YEAR>_txt.zip        # original archive
    EPH_usu_<…>_Trim_<YEAR>_txt/*.txt      # unzipped (when unzip=True)
    metadata.json                          # provenance
```

### `metadata.json` shape

```json
{
  "source": "INDEC - EPH - Microdatos (formato TXT)",
  "page_url": "https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos-1",
  "ftp_root": "https://www.indec.gob.ar/ftp/cuadros/menusuperior/eph/",
  "dataset_name": "EPH_usu_3_Trim_2025_txt",
  "fully_qualified_name_suggestion": "indec.mercado_laboral.EPH_usu_3_Trim_2025_txt",
  "year": 2025,
  "quarter": 3,
  "format": "txt",
  "file": {
    "name": "EPH_usu_3_Trim_2025_txt.zip",
    "path": "/data-local/indec/mercado_laboral/EPH/2025/Q3/EPH_usu_3_Trim_2025_txt.zip",
    "bytes": 2940149,
    "sha256": "…",
    "etag": "…",
    "last_modified": "…",
    "content_type": "application/x-zip-compressed",
    "from_cache": false
  },
  "unzipped_files": [
    "EPH_usu_3er_Trim_2025_txt/usu_hogar_T325.txt",
    "EPH_usu_3er_Trim_2025_txt/usu_individual_T325.txt"
  ],
  "fetched_at_utc": "2026-…Z"
}
```

Use `fully_qualified_name_suggestion` as the starting FQN for catalog registration (you can override with any project convention).

## Recommended flow

1. **List first** (no download):

   ```
   scrapper_indec_mercado_laboral_list(period="Microdatos (2025)")
   ```

   Confirm total bytes and quarters with the user when the range is large (more than ~4 quarters).

2. **Download** (writes ZIP + TXT + `metadata.json`):

   ```
   scrapper_indec_mercado_laboral_download(period="Microdatos (2025)")
   ```

   Use `overwrite=True` only when the user asks to refresh. Leave `unzip=True` (default) so DuckDB can read the TXT directly.

3. **Ingest** (warehouse, per `./skills/ingest-indec-mercadolaboral/SKILL.md`): **`gold.indec_eph_usu_hogar`** and **`gold.indec_eph_usu_individual`** only; **`delim=';'`**, **`decimal_comma=true`**, bootstrap with **`CREATE TABLE IF NOT EXISTS … AS SELECT * … LIMIT 0`** then **`INSERT INTO … SELECT *`**; **one SQL statement per `duckdb_warehouse_query`**. Resolve the exact **`/data-local/.../usu_hogar_*.txt`** / **`usu_individual_*.txt`** path after unzip (folder layout varies).

4. **Register** (catalog, per `./skills/update-catalog/SKILL.md`). Use the `fully_qualified_name_suggestion` from `metadata.json`, record columns from `PRAGMA table_info`, and include **lineage** from the ZIP URL to the warehouse table.

## Don'ts

- **Don't** call `duckdb_warehouse_query` with `read_csv_auto('https://www.indec.gob.ar/…')` — INDEC returns a 36 KB SPA shell when the path is missing, which DuckDB will happily read as a malformed CSV, and you lose `sha256` / `metadata.json` / lineage.
- **Don't** shell out to `curl` / `wget` from inside a tool call. Use `scrapper_indec_mercado_laboral_download`.
- **Don't** extend the scraper with ad-hoc URL patterns without adding HEAD-verified examples. The SPA fallback makes 200-OK-but-missing responses trivial to hit; the scraper's HEAD + first-chunk magic-byte check is what prevents silent data corruption.
