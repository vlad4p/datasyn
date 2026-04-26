---
name: ingest-indec-mercadolaboral
description: >-
  Ingest INDEC EPH mercado laboral microdata from /data-local/indec/mercado_laboral
  into exactly two tables in gold: indec_eph_usu_hogar and indec_eph_usu_individual.
  MUST use two separate duckdb_warehouse_query calls per role: (1) CREATE TABLE IF
  NOT EXISTS gold.<t> AS SELECT * FROM read_csv_auto(..., delim=';', header=true,
  quote='"', decimal_comma=true, sample_size=-1) LIMIT 0; (2) INSERT INTO gold.<t>
  SELECT * FROM read_csv_auto(...). NEVER use CREATE TABLE IF NOT EXISTS ... AS
  SELECT * without LIMIT 0 — when the table exists DuckDB skips AS SELECT and the
  load silently reports success with stale COUNT(*). Never one table per quarter;
  period lives in row columns ANO4 + TRIMESTRE. Overrides AGENTS.md bronze hint.
  Use for INDEC, EPH, mercado laboral, usu_hogar, usu_individual, ingesta EPH.
---

# Ingest INDEC mercado laboral (EPH microdata → catalog + DuckDB)

## TL;DR — the only allowed ingest SQL (copy these two calls per file)

Fill in **`<DATA_LOCAL_TXT_PATH>`** (e.g. **`/data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_hogar_T125.txt`**). Run as **two** separate **`duckdb_warehouse_query`** calls — the second call is where rows arrive, **always**.

```sql
-- Call 1 — bootstrap (idempotent; LIMIT 0 = DDL only, no rows). Run once per role.
CREATE TABLE IF NOT EXISTS gold.indec_eph_usu_hogar AS
SELECT *
FROM read_csv_auto('<DATA_LOCAL_TXT_PATH>', delim=';', header=true, quote='"', decimal_comma=true, sample_size=-1)
LIMIT 0;
```

```sql
-- Call 2 — data. Run for every file/quarter (first load and every subsequent one).
INSERT INTO gold.indec_eph_usu_hogar
SELECT *
FROM read_csv_auto('<DATA_LOCAL_TXT_PATH>', delim=';', header=true, quote='"', decimal_comma=true, sample_size=-1);
```

Mirror both calls with table **`gold.indec_eph_usu_individual`** and path **`usu_individual_*.txt`**. Validate: `SELECT COUNT(*) FROM gold.indec_eph_usu_hogar` **and** `SELECT COUNT(*) FROM gold.indec_eph_usu_individual` — **do not** reuse a prior **`COUNT(*)`** as evidence of a new load.

## TL;DR — the silent-failure anti-pattern (STOP before emitting this)

```sql
-- WRONG. If the table already exists (e.g. loaded Q3 before), DuckDB executes
-- ONLY the CREATE with no AS SELECT body. Zero rows are inserted; COUNT(*) still
-- returns the previous quarter. Agent then reports success with stale numbers.
CREATE TABLE IF NOT EXISTS gold.indec_eph_usu_hogar AS
SELECT * FROM read_csv_auto('/data-local/.../usu_hogar_T125.txt', delim=';');
```

Same rule for **`gold.indec_eph_usu_individual`** and for any multi-statement string that chains **`CREATE SCHEMA …; CREATE TABLE …; CREATE TABLE …;`** in one **`duckdb_warehouse_query`** call.

---

End-to-end workflow for **INDEC Encuesta Permanente de Hogares (EPH)** user microdata files under `**/data-local/indec/mercado_laboral/`** (repo: `./data-local/indec/mercado_laboral/`). Files are `**.txt**` with **semicolon** delimiters, **double-quoted** headers and fields, and often **comma as decimal separator** in numeric columns.

### Delimiter: semicolon (`;`) — never tab (`\t`)

INDEC EPH **usu_hogar** / **usu_individual** microdata is **semicolon-separated**, not TSV.

- **Always** pass **`delim = ';'`** (or **`delim=';'`**) explicitly in **`read_csv_auto`** / **`read_csv`** for every ingest.
- **Never** use **`delim='\t'`** or rely on a **default** delimiter: models sometimes emit tab for “`.txt` files”; that **mis-parses** the file (often one or few wide columns) and corrupts the load.
- **Pandas:** **`sep=';'`** (not **`sep='\t'`**).

Wrong (Langfuse-style anti-example): `read_csv_auto('.../usu_hogar_T125.txt', delim='\t')`. Correct: include **`delim = ';'`**, **`header = true`**, **`quote='"'`**, and usually **`decimal_comma = true`** as in §2 and §5 templates.

### Important: two tables total — not one table per quarter

For this skill, the warehouse must expose **exactly two physical table names** in **`gold`** (and no other tables for EPH usuarios loads):

- **Hogar** → **`gold.indec_eph_usu_hogar`**
- **Individual** → **`gold.indec_eph_usu_individual`**

**Do not** create tables whose names encode a quarter or year (e.g. **`…_2025_q1`**, **`…_T125`**, **`eph_hogar_q1`**). There is **no** **`gold.indec_eph_usu_hogar_q1`** (or similar). **Survey year and quarter are already in each row:** every EPH usuarios file includes **`ANO4`** (year) and **`TRIMESTRE`** (quarter). **Do not** add extra **`year`** / **`quarter`** columns in **`INSERT`** / **`SELECT`** — use **`SELECT *`** from **`read_csv_auto`** only. For **catalog** **`ingestHistory`**, still record period from the path or **`metadata.json`** (see §4, §6).

**Every quarter (and every year):** **`INSERT INTO`** the **same** **`gold.indec_eph_usu_hogar`** or **`gold.indec_eph_usu_individual`** so all periods stack in one table per role. Once per role, **`CREATE TABLE IF NOT EXISTS … AS … LIMIT 0`** defines the empty shell; **every** data load (including the first) uses **`INSERT`** (§5).

**Warehouse rule (fixed targets):** Use **schema `gold` only** — no **`bronze`**, **`silver`**, **`raw`**, or ad hoc schemas for this pipeline. The **only** warehouse objects created or appended for EPH usuarios microdata are these two **table names** (qualified as **`gold.indec_eph_usu_hogar`** and **`gold.indec_eph_usu_individual`**), shared across **all** years and quarters (Q1…Q4):

| Source file pattern | DuckDB object |
|---------------------|----------------|
| **`usu_hogar_*.txt`** | **`gold.indec_eph_usu_hogar`** |
| **`usu_individual_*.txt`** | **`gold.indec_eph_usu_individual`** |

**Create if not exists, then append (recommended pattern):** For each role (**hogar** / **individual**), use **`CREATE TABLE IF NOT EXISTS gold.<table> AS SELECT * FROM read_csv_auto(...) LIMIT 0`** once (idempotent). **Every** file—including the first—uses **`INSERT INTO gold.<table> SELECT * FROM read_csv_auto(...)`** so rows **append**; survey period is in **`ANO4`** / **`TRIMESTRE`**, not extra projected columns.

Do **not** use **`CREATE TABLE IF NOT EXISTS … AS SELECT …`** **without `LIMIT 0`** as the **only** way to ingest each new file: when the table already exists, DuckDB **does not run** the **`AS SELECT`** body, so new files would never load. **`LIMIT 0`** is for **DDL / column layout only**; **data** always arrives via **`INSERT`**.

Example: host path `data-local/.../EPH/2025/Q1/.../usu_hogar_T125.txt` → SQL path `/data-local/.../usu_hogar_T125.txt` → rows go into **`gold.indec_eph_usu_hogar`** alongside other quarters/years. Do **not** create per-period or per-file warehouse tables.

### Why runs sometimes land in `bronze` (and why that is wrong here)

**`AGENTS.md`** describes a medallion layout and says to **prefer `bronze` for new file loads** in the **generic** warehouse workflow. Models and traces often generalize that to “ingest files → `bronze`”. **This skill is an explicit exception:** for INDEC EPH usuarios under **`indec/mercado_laboral`**, the **only** allowed load targets are **`gold.indec_eph_usu_hogar`** and **`gold.indec_eph_usu_individual`**. If this skill applies, **do not** follow the generic bronze default.

**Root causes (wrong SQL in Langfuse-style traces):**

1. **System prompt bias** — the supervisor loads the full **`AGENTS.md`**; the generic line “prefer **`bronze`** for new file loads” applies unless the **INDEC exception** block is followed.
2. **Wrong skill pointer (fixed in repo)** — earlier versions of **Scraper discipline** step 3 and the now-deleted **`ingest-csv`** skill implied a generic CSV workflow for EPH; that invited improvised **`bronze.eph_*_YYYY_qN`** tables. Today the **only** ingest skill for **`/data-local/indec/mercado_laboral/EPH/...`** paths is **this** one; there is no **`ingest-csv`** skill anymore.
3. **`fqn_suggestion` in `metadata.json`** — describes the **zip / folder** naming convention, **not** the warehouse table FQN; using it as a table name yields wrong catalog and wrong mental model.
4. **Convenience SQL** — chaining **`CREATE SCHEMA` + two `CREATE TABLE`** in one string violates **one statement per `duckdb_warehouse_query`** and hides review.
5. **Wrong delimiter** — **`read_csv_auto(..., delim='\t')`** or omitting **`delim`** so DuckDB guesses tab/CSV defaults. EPH usuarios **must** use **`delim = ';'`**.

**Repo alignment (do not delete this skill):** **`AGENTS.md`** states the INDEC exception and scraper discipline; **`agent/graph.py`** injects **`/skills/ingest-indec-mercadolaboral`** (and scrape + catalog skills). The previous **`skills/ingest-csv/`** folder has been removed — generic CSV / TXT loads are handled directly with **`duckdb_warehouse_query`** per **`AGENTS.md`** → **Ingest and delimited data**.

**Forbidden anti-patterns** (real failure mode: one SQL string with `bronze`, per-quarter table names, and catalog FQNs without `main` / `gold`):

| Wrong | Why |
|--------|-----|
| **`CREATE SCHEMA … bronze`** / **`CREATE TABLE bronze.…`** for this ingest | Schema must be **`gold`**, not medallion **`bronze`**. |
| Tables like **`bronze.eph_hogar_2025_q1`**, **`gold.indec_eph_usu_hogar_2025_q1`** | Period must not be in the **table name**. **Only** **`indec_eph_usu_hogar`** and **`indec_eph_usu_individual`**; filter by **`ANO4`** / **`TRIMESTRE`** in SQL; log path period in catalog **`ingestHistory`**. |
| **`CREATE TABLE IF NOT EXISTS bronze.eph_* AS SELECT …`** (no **`LIMIT 0`**) as the only load per file | Wrong schema/names; and **`IF NOT EXISTS … AS`** without **`LIMIT 0`** skips **`SELECT`** when the table exists—use **`LIMIT 0`** for bootstrap, **`INSERT`** for data. |
| **`duckdb-warehouse.bronze.eph_hogar_2025_q1`** (or any FQN without **`main`** and **`gold`**) in the catalog | Catalog must register **`duckdb-warehouse.main.gold.indec_eph_usu_hogar`** / **`…_individual`** only. |
| Multiple statements in one **`duckdb_warehouse_query`** (e.g. `CREATE SCHEMA; CREATE TABLE; CREATE TABLE`) | **`AGENTS.md`**: **one statement per call** — split into separate invocations. |
| **`read_csv_auto(..., delim='\t')`** or **`read_csv_auto('...')`** with no **`delim`** | EPH TXT is **`;`**-separated. Use **`delim = ';'`** always (see **Delimiter** above). |

**Pre-flight checklist** (must be true before running ingest SQL):

- [ ] **`read_csv_auto`** includes **`delim = ';'`** (not **`'\t'`**, not omitted).
- [ ] Schema: **`CREATE TABLE IF NOT EXISTS … AS … LIMIT 0`** (or equivalent) before first **`INSERT`**; all periods use **`INSERT`** into the same **`gold.indec_eph_usu_*`** table.
- [ ] Every created/inserted object is qualified **`gold.indec_eph_usu_hogar`** or **`gold.indec_eph_usu_individual`** (no **`bronze.`**, **`silver.`**, or **`raw.`** for this pipeline).
- [ ] Table names are **exactly** **`indec_eph_usu_hogar`** and **`indec_eph_usu_individual`** — no suffix for quarter/year (not **`…_q1`**, not **`…_2025`**, not **`…_T125`**).
- [ ] Catalog **`fully_qualified_name`** uses **`duckdb-warehouse.main.gold.<table>`**.

**Related:** **`./skills/update-catalog/SKILL.md`** and **`./skills/catalog-sql/SKILL.md`** (catalog SQL only via **`catalog_execute_query`**). Generic non-INDEC CSV / TXT loads: use **`duckdb_warehouse_query`** directly per **`AGENTS.md`** → **Ingest and delimited data** — there is no separate **`ingest-csv`** skill.

---

## Scope and tools


| Step                 | Server    | Tool                                                                               |
| -------------------- | --------- | ---------------------------------------------------------------------------------- |
| List / resolve paths | `duckdb`  | `**duckdb_data_local_ls**` (recursive under `/data-local/indec/mercado_laboral`)   |
| Ingest + validate    | `duckdb`  | `**duckdb_warehouse_list_tables**`, `**duckdb_warehouse_query**`                   |
| Catalog              | `catalog` | `**catalog_get_schema**` (once per session if needed), `**catalog_execute_query**` |


Do **not** invent catalog helpers beyond SQL; see `**AGENTS.md`** catalog discipline.

### Warehouse lock and SQL batching

If `**duckdb_get_schema**` or `**duckdb_warehouse_query**` fails with an **IO Error / could not set lock** on `**/data/warehouse.duckdb`**, another container (usually `**duckdb-ui**`) still holds the file. See `**AGENTS.md**` (warehouse file lock): default compose omits the UI profile; stop `**duckdb-ui**` or avoid `**--profile ui**` during ingest.

Use **one statement per `duckdb_warehouse_query`** (e.g. two calls for hogar + individual `CREATE TABLE`, not one string with two semicolon-terminated statements).

---

## 1. Resolve the dataset file(s)

- **Mount:** DuckDB only sees `**/data-local/...`**. Map repo paths like `data-local/indec/mercado_laboral/EPH/2025/Q1/.../usu_hogar_T125.txt` → `**/data-local/indec/mercado_laboral/EPH/2025/Q1/.../usu_hogar_T125.txt**`.
- Layout varies: files may sit under `**EPH/<year>/<Qn>/**` directly or inside a subfolder (e.g. `**EPH_usu_1er_Trim_2025_txt/**`). Use `**duckdb_data_local_ls**` until the exact `**usu_hogar_*.txt**` / `**usu_individual_*.txt**` path is known.
- **First ingest target:** When the user names a “dataset”, treat the **first concrete file path** they give (or the first matching `**.txt`** under that quarter folder) as the primary file; **discover physical schema from that file** (header + first rows).

---

## 2. Discover schema (read first element / first rows)

1. **Header:** First line is the column list (quoted names separated by `**;`**).
2. **Probe** without loading everything if needed: `**read_csv_auto`** with a row cap in a CTE, or `**duckdb_warehouse_query**` with `LIMIT 5`, or pandas `**pd.read_csv(..., sep=';', nrows=5000, low_memory=False)**` on the same `**/data-local/...**` path the container uses.
3. **DuckDB read options** (EPH usuarios TXT is consistently — **delimiter is always semicolon, never tab**):
  - **`delim = ';'`** (required in SQL; do not use **`delim='\t'`** or skip **`delim`** and let DuckDB guess)
  - **`header=true`**
  - **`quote='"'`**
  - **`sample_size=-1`** (large files: helps type detection when safe)
  - If you see European decimals (e.g. `**466666,67**`), set **`decimal_comma=true`** on **`read_csv_auto`** / **`read_csv`** so amounts parse correctly.
4. **Survey period in the file (no extra columns in SQL):** EPH usuarios microdata **always** includes **`ANO4`** (survey year) and **`TRIMESTRE`** (survey quarter). **Do not** project path-based **`year`** / **`quarter`** into the warehouse **`INSERT`** — load **`SELECT *`** from **`read_csv_auto`** so **`ANO4`** / **`TRIMESTRE`** stay the single source of truth in the table. Use them for **`WHERE`**, **`DELETE`** slices, and joins across appended files.

---

## 3. Read `metadata.json` (Python `json` module)

Do **not** treat `**metadata.json`** as opaque prose: load it with `**import json**` and a `**Path**` so fields are real dict values for the catalog and for cross-checks.

For a TXT under `**.../EPH/<year>/<Qn>/...**`, `**metadata.json**` lives in that `**<Qn>**` directory (same level as optional unzip subfolders), e.g. host repo path `**.../data-local/indec/mercado_laboral/EPH/2025/Q1/metadata.json**`.

**Required pattern:** resolve the quarter directory from the ingest file path, then `**json.load`** from a UTF-8 text stream:

```python
import json
from pathlib import Path


def load_eph_metadata_json(data_txt_path: Path) -> dict:
    """data_txt_path: host Path to the .txt (e.g. .../data-local/indec/mercado_laboral/EPH/2025/Q1/.../usu_hogar_T125.txt)."""
    parts = data_txt_path.resolve().parts
    q_idx = next((i for i, p in enumerate(parts) if p in ("Q1", "Q2", "Q3", "Q4")), None)
    if q_idx is None:
        raise FileNotFoundError("No Q1–Q4 segment in path; cannot locate metadata.json")
    quarter_dir = Path(*parts[: q_idx + 1])
    meta_path = quarter_dir / "metadata.json"
    with meta_path.open(encoding="utf-8") as f:
        return json.load(f)


# Example:
# meta = load_eph_metadata_json(Path("/path/to/data-local/indec/mercado_laboral/EPH/2025/Q1/.../usu_hogar_T125.txt"))
# page_url = meta.get("page_url")
```

Typical keys (use what is present): `**source**`, `**page_url**`, `**ftp_root**`, `**dataset_name**`, `**fully_qualified_name_suggestion**`, `**year**`, `**quarter**`, `**format**`, `**file**` (name, path, bytes, sha256), `**unzipped_files**`, `**fetched_at_utc**`.

Use `**meta**` to build:

- `**description**` (catalog): 2–4 sentences — what INDEC published, period (year/quarter), microdata level (**hogar** vs **individual**), and link to `**page_url`** / `**ftp_root**` when useful.
- `**displayName**`: human label, e.g. **“INDEC EPH — usu hogar — 2025 Q1”**.
- `**sourceUrl`** / `**customProperties**`: canonical `**page_url**`, path to `**metadata.json**`, original zip `**file.path**`, `**sha256**`, `**dataset_name**`.

Cross-check: `**metadata.json**` **`year`** / **`quarter`** (if present) should align with path segments **`.../EPH/<year>/Q<n>/...`** for documentation; warehouse rows already carry **`ANO4`** / **`TRIMESTRE`** from the file.

---

## 4. Path / `metadata.json` period (catalog and checks — not for warehouse `INSERT`)

Parse segments after **`mercado_laboral/EPH/`** when you need a **human** period label or **`ingestHistory`** fields:

- **Calendar / folder year:** four-digit directory (e.g. **`2025`**).
- **Folder quarter:** **`Q1`…`Q4`** → integer **`1`…`4`** (or string **`"Q1"`** for display).

Examples:

- **`/data-local/.../EPH/2025/Q1/.../usu_hogar_T125.txt`** → document as **2025 Q1** in **`ingestHistory`**; SQL **`INSERT`** is still **`SELECT *`** (rows include **`ANO4`**, **`TRIMESTRE`**).
- **`.../usu_individual_T125.txt`** → same path parsing; load into **`gold.indec_eph_usu_individual`**.

If path parsing fails for catalog text, fall back to **`metadata.json`** **`year`** / **`quarter`**.

---

## 5. DuckDB ingest

1. **`CREATE SCHEMA IF NOT EXISTS gold`** (init usually already created **`gold`**; this keeps runs idempotent.) **Do not** create tables in any schema other than **`gold`** for this ingest.
2. **Exact table names** (mandatory — **only** these two physical names in **`gold`**; **never** derive the table name from quarter or year):

   - Hogar → **`gold.indec_eph_usu_hogar`**
   - Individual → **`gold.indec_eph_usu_individual`**

3. **Bootstrap schema, then insert every quarter:** Use **`CREATE TABLE IF NOT EXISTS`** with **`LIMIT 0`** (see templates below) so the table exists **before** the first **`INSERT`**. **Every** file load—including the first—is **`INSERT INTO gold.<table> SELECT * FROM read_csv_auto(...)`** (no extra projected columns). Period in data = **`ANO4`** / **`TRIMESTRE`**. Optional re-load: **`DELETE FROM gold.<table> WHERE ANO4 = <Y> AND TRIMESTRE = <T>`** then **`INSERT`** (use the survey types/casts your table has). **Never** create a new table per quarter.
4. **SQL shape — path and period are per file, never copy-pasted**

**Delimiter again:** every **`read_csv_auto`** for these files **must** include **`delim = ';'`** alongside **`header`**, **`quote`**, and usually **`decimal_comma = true`**. Omitting **`delim`** or using **`'\t'`** is an ingest error.

The string passed to **`read_csv_auto(...)`** is **different for every ingest**: quarter folders differ, inner folder names differ, and filenames differ. **`duckdb_data_local_ls`** (or the user’s path) gives the **canonical** **`/data-local/indec/mercado_laboral/EPH/.../*.txt`** for **this** run.

Use the **same** **`read_csv_auto`** options on bootstrap and on every **`INSERT`**. Substitute only **`'<DATA_LOCAL_TXT_PATH>'`** per file (double any **`'`** inside paths).

**A) Bootstrap — create table if not exists (zero rows, defines schema)**

Run once per role (any representative **`.txt`** for that role). **`SELECT *`** matches the file columns (**`ANO4`**, **`TRIMESTRE`**, etc.) — **no** appended **`year`** / **`quarter`**.

```sql
CREATE TABLE IF NOT EXISTS gold.indec_eph_usu_hogar AS
SELECT *
FROM read_csv_auto(
  '<DATA_LOCAL_TXT_PATH>',
  delim = ';',
  header = true,
  quote = '"',
  decimal_comma = true,
  sample_size = -1
)
LIMIT 0;
```

Mirror with **`gold.indec_eph_usu_individual`** and a **`usu_individual_*.txt`** path when bootstrapping the individual table.

**Examples of valid `<DATA_LOCAL_TXT_PATH>` values (each is a different ingest):**

- `**/data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_hogar_T125.txt`**
- `**/data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_individual_T125.txt**`
- `**/data-local/indec/mercado_laboral/EPH/2024/Q2/EPH_usu_2_Trim_2024_txt/usu_hogar_T224.txt**`
- `**/data-local/indec/mercado_laboral/EPH/2025/Q2/usu_hogar_T225.txt**` (file directly under `**Q2**`)

Use `**gold.indec_eph_usu_individual**` and the matching path when the source file is `**usu_individual_*.txt**`.

**Insert — every file (append; period is `ANO4` / `TRIMESTRE` in each row)**

Use **`SELECT *`** only — **do not** append path-based **`year`** / **`quarter`** columns.

Example for "'/data-local/indec/mercado_laboral/EPH/2025/Q2/usu_hogar_T225.txt'"
```sql
INSERT INTO gold.indec_eph_usu_hogar
SELECT *
FROM read_csv_auto(
  '/data-local/indec/mercado_laboral/EPH/2025/Q2/usu_hogar_T225.txt',
  delim = ';',
  header = true,
  quote = '"',
  decimal_comma = true,
  sample_size = -1
);
```

Swap the path and table name for each ingest (**`usu_individual_*.txt`** → **`gold.indec_eph_usu_individual`**). Run that role’s **`CREATE TABLE IF NOT EXISTS … LIMIT 0`** once before the first **`INSERT`** if the table does not exist.

**Minimal read options (only when you have verified types):** `**read_csv_auto('…', delim=';', header=true)**` is acceptable for probes; for production loads keep **`quote`**, **`decimal_comma`**, and **`sample_size`** as above unless a file proves otherwise.

5. **Append vs replace:** Routine loads are **`INSERT … SELECT *`** (after optional **`CREATE IF NOT EXISTS … LIMIT 0`**). To replace one survey slice, **`DELETE FROM gold.<table> WHERE ANO4 = <survey_year> AND TRIMESTRE = <survey_quarter>`** (adjust types/casts to match **`PRAGMA table_info`**) then **`INSERT`** again. Full rebuild: **`DROP TABLE …`** then **`CREATE … LIMIT 0`** + **`INSERT`**s.

6. **Validate:** **`COUNT(*)`**, **`SELECT * … LIMIT 10`**, **`PRAGMA table_info('gold.indec_eph_usu_hogar')`**, and spot-check **`ANO4`**, **`TRIMESTRE`**. If **`PRAGMA table_info`** shows one very wide column, re-run with **`delim = ';'`** (wrong delimiter).

---

## 6. Register / update the catalog (`entity_json`)

Follow **`./skills/update-catalog/SKILL.md`**: introspect columns with **`duckdb_warehouse_query`** (`PRAGMA table_info('gold.<table>')` or **`information_schema.columns`**), build **`columns`** with **`name`**, **`dataType`**, **`description`**, then upsert.

### Mandatory sequence (no empty `columns`, Langfuse-safe)

1. **`duckdb_warehouse_query`**: build the **`columns`** array from the warehouse (never ship **`"columns": []`** if the table exists). DuckDB can emit JSON in one shot, e.g.  
   `WITH ordered AS (SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'gold' AND table_name = 'indec_eph_usu_hogar' ORDER BY ordinal_position) SELECT json_group_array(json_object('name', column_name, 'dataType', data_type, 'description', '')) FROM ordered`  
   (mirror for **`indec_eph_usu_individual`**), then map into **`entity_json.columns`**.
2. **`catalog_execute_query`**: `SELECT id, entity_json FROM dataset_entity WHERE fully_qualified_name = '<fqn>'` and **merge** into the prior document (preserve prior **`ingestHistory`** entries when appending a new quarter).
3. **One upsert per FQN:** `INSERT INTO dataset_entity (fully_qualified_name, entity_json) VALUES ('<fqn>', '<json>'::jsonb) ON CONFLICT (fully_qualified_name) DO UPDATE SET entity_json = EXCLUDED.entity_json RETURNING id` — do **not** pair a bare **`UPDATE`** on one FQN with a bare **`INSERT`** on the other unless you are certain both paths stay idempotent.
4. **OpenData / gobierno mínimo:** set **`fullyQualifiedName`**, **`service`**, **`database`**, **`schema`**, **`sourceUrl`** (INDEC portal), **`customProperties.publisher`**, **`customProperties.ingestHistory`** ( **`dataLocalTxtPath`**, **`metadataJsonPath`**, **`year`**, **`quarter`**, **`sourceSha256`** / **`pageUrl`** from **`metadata.json`** when present), **`customProperties.domain`** / **`dataProduct`**.
5. **`tag_usage`:** after **`RETURNING id`**, refresh tags per **`./skills/update-catalog/SKILL.md`** (e.g. **`Source.INDEC`**, **`Survey.EPH`**).

**Host repair utility (sparse catalog rows):** if legacy **`dataset_entity`** rows exist with **`columns: []`** or missing tags / **`ingestHistory`**, follow **`./skills/update-catalog/SKILL.md`** → **Host repair utility (INDEC EPH gold)** and run **`scripts/repair_eph_dataset_entity.py`** (commands and Docker variant are documented there).

**Do not** register **`bronze`** tables, per-quarter warehouse names, or extra **`gold`** tables for EPH usuarios. **Exactly two** catalog datasets (one per physical table): **`duckdb-warehouse.main.gold.indec_eph_usu_hogar`** and **`duckdb-warehouse.main.gold.indec_eph_usu_individual`** — not **`…_2025_q1`**. See **Why runs sometimes land in `bronze`** above.

**Upsert shape:**

```sql
INSERT INTO dataset_entity (fully_qualified_name, entity_json) VALUES (...)
ON CONFLICT (fully_qualified_name) DO UPDATE SET entity_json = EXCLUDED.entity_json RETURNING id
```

**FQN** (stable; database **`main`**, schema **`gold`**, tables **`indec_eph_usu_hogar`** / **`indec_eph_usu_individual`**):

- Hogar: **`duckdb-warehouse.main.gold.indec_eph_usu_hogar`**
- Individual: **`duckdb-warehouse.main.gold.indec_eph_usu_individual`**

Mirror `**fullyQualifiedName**`, `**service**`, `**database**`, `**schema**` (`**{ "name": "gold" }**`), `**name**` in `**entity_json**` per `**./skills/catalog-sql/SKILL.md**`.

### Ingest history / load log (every file)

**Create the catalog row if it does not exist** (first ingest for that table): same upsert **`INSERT … ON CONFLICT … DO UPDATE`**.

**On every successful load** of a file into `**gold.indec_eph_usu_hogar`** or `**gold.indec_eph_usu_individual**`, update metadata so consumers see a **chronological log** of what was loaded:

1. `**SELECT id, entity_json FROM dataset_entity WHERE fully_qualified_name = '<fqn>'`** (if missing, the upsert creates the base document).
2. Merge into `**entity_json.customProperties.ingestHistory**` (array stored under `**customProperties**`, same document as `**domain**` / `**dataProduct**` per `**./skills/catalog-sql/SKILL.md**`):
  - `**ingestHistory**`: array of objects, **newest-first** or sorted by path period — pick one convention and keep it stable. Keys like **`year`** / **`quarter`** here are **catalog JSON only** (from §4 path or **`metadata.json`**), **not** warehouse columns.
  - Each object should include at least: **`year`**, **`quarter`** (int, from path/meta for the log), **`quarterLabel**` (e.g. **`"Q1"`**), **`dataLocalTxtPath`**, **`metadataJsonPath`**, **`ingestedAtUtc`**, optional **`rowCount`** after **`INSERT`**, optional **`ANO4`** / **`TRIMESTRE`** from the file for cross-check.
  - If `**metadata.json**` (§3) has `**file.sha256**`, `**fetched_at_utc**`, `**page_url**`, copy them into the same object for audit (`**sourceSha256**`, `**fetchedAtUtc**`, `**pageUrl**`).
3. **De-dupe:** If `**customProperties.ingestHistory`** already has an entry for the same **`year`** / **`quarter`** (log fields) and **`dataLocalTxtPath`** (or same **`sourceSha256`** when present), **replace** that element instead of duplicating (re-load scenario).
4. Refresh `**description`** / `**displayName**` if needed (e.g. “INDEC EPH — usu hogar — multi-period table (gold)”) without dropping `**columns**`, `**tags**`, or `**upstreamLineage**` — merge from the prior row.

Then refresh `**tag_usage**` / lineage per `**./skills/update-catalog/SKILL.md**`.

### Governance (OpenMetadata-style, [Governance API index](https://docs.open-metadata.org/v1.12.x/api-reference/governance))

The catalog stores a flexible `**entity_json**` JSONB (see `**catalog/migrations/001_dataset_entity.sql**`). Populate **governance-oriented** fields so they align with OpenMetadata concepts (**domains**, **tags/classifications**, **glossary terms**, **ownership**, **data product context**), even if the UI only summarizes a subset:


| OM concept                 | Where to store in this project                                                                                                                                                                                                                                                                        |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Domain** (business area) | `**customProperties`**: e.g. `**domain**`, `**domainDisplayName**` (“Mercado laboral — Argentina”), `**dataProduct**` (“INDEC EPH microdatos usuarios”).                                                                                                                                              |
| **Tags / classifications** | `**entity_json.tags`**: `[{ "tagFQN": "Source.INDEC", "source": 0 }, { "tagFQN": "Survey.EPH", "source": 0 }]` — use consistent FQNs your org defines; `**source**`: `**0**` = classification, `**1**` = glossary (see `**tag_usage**` migration).                                                    |
| **Glossary terms**         | `**entity_json.glossaryTerms`**: `[{ "name": "...", "displayName": "...", "description": "..." }]` or minimal objects that match your UI expectations; mirror the same tags into `**tag_usage**` via `**DELETE` + `INSERT**` after upsert (`**./skills/update-catalog/SKILL.md**`).                   |
| **Owners**                 | `**entity_json.owners`**: `[{ "name": "...", "type": "team" }]` when known; otherwise `**[]**`.                                                                                                                                                                                                       |
| **Lineage**                | `**upstreamLineage`** / `**downstreamLineage**` / `**sourceUrl**`: latest or consolidated upstream `**/data-local/...**` file path; use `**customProperties.ingestHistory**` for the full per-file log; optional `**customProperties.lastMetadataJsonPath**` for the quarter touched in the last run. |


Always `**SELECT id, entity_json FROM dataset_entity WHERE fully_qualified_name = '<fqn>'**` before updates to merge lineage, `**customProperties.ingestHistory**`, and tags.

---

## 7. What to report back

Before writing the summary, **prove the load actually happened**:

- Run `SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE ANO4 = <year> AND TRIMESTRE = <quarter>) AS loaded_slice FROM gold.indec_eph_usu_hogar` and the same for **`…_individual`**. **`loaded_slice > 0`** for the period you just ingested is the only valid success signal. A stale total with **`loaded_slice = 0`** means the `INSERT` did not run (almost always the `IF NOT EXISTS … AS SELECT` silent-skip anti-pattern — revert to the two-call TL;DR).
- **Do not** copy a COUNT observed before the ingest and present it as the post-ingest count.

Then report:

1. Resolved **`/data-local/...`** path(s), period for **catalog** (§4 / **`metadata.json`**), **`ANO4`/`TRIMESTRE`** sanity in data, and highlights from **`meta`**.
2. Whether **`delim = ';'`** and **`decimal_comma`** were set (never **`delim='\t'`**).
3. DuckDB `**gold.<table>**`, **total row count**, **`loaded_slice`** count for (`ANO4`, `TRIMESTRE`) of this ingest, and a **`LIMIT 5`** sample.
4. Catalog **FQN**, confirmation `**customProperties.ingestHistory`** was appended/merged for **year** / **quarter** / paths, and `**tag_usage`** (and lineage if used) were refreshed.

---

## Quick reference — example paths


| File                        | Table                               | FQN suffix                             |
| --------------------------- | ----------------------------------- | -------------------------------------- |
| `**usu_hogar_T*.txt**`      | `**gold.indec_eph_usu_hogar**`      | `**...gold.indec_eph_usu_hogar**`      |
| `**usu_individual_T*.txt**` | `**gold.indec_eph_usu_individual**` | `**...gold.indec_eph_usu_individual**` |


**Examples:**

- `**data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_hogar_T125.txt`**
- `**data-local/indec/mercado_laboral/EPH/2025/Q1/EPH_usu_1er_Trim_2025_txt/usu_individual_T125.txt**`

---

**Summary:** Resolve **`/data-local/...`** → load **`metadata.json`** (§3) → **`read_csv_auto(..., delim = ';', ...)`** (never tab). In **`gold`**, **`CREATE IF NOT EXISTS … SELECT * … LIMIT 0`** then **`INSERT … SELECT *`** only — period in-table = **`ANO4`** / **`TRIMESTRE`** (§5). Catalog: path period in **`ingestHistory`** (§4, §6), FQNs **`duckdb-warehouse.main.gold.<table>`**, **`tag_usage`** per **`update-catalog`**.