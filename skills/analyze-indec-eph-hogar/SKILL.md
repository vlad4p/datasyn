---
name: analyze-indec-eph-hogar
description: >-
  Produce reproducible analyses of the INDEC EPH household microdata table
  `gold.indec_eph_usu_hogar` using `duckdb_execute_query` for SQL aggregates
  and `silver.indec_mercado_laboral_variables` (field `campo`) as the column
  dictionary. The brain pushes all heavy work into DuckDB SQL, writes a
  markdown report and a runnable Python (pandas + matplotlib) script under
  `reports/indec_eph_usu_hogar/<topic>/` via `write_file`, and ALWAYS asks
  one focused question (focus + window) before plotting unless the user
  already specified both. Use when the user asks to analyze / explore /
  visualize / make a report / "análisis" on `indec_eph_usu_hogar`,
  `indec_usu_hogar`, EPH hogares, microdatos de hogares INDEC, or names
  household-level variables (ITF, IPCF, REGION, AGLOMERADO, IV*, II*) over
  EPH data. Does NOT cover individuos (`indec_eph_usu_individual`).
---

# Análisis de `gold.indec_eph_usu_hogar` (brain)

Turns *"analizá los hogares de la EPH"* / *"hacé un análisis de
`gold.indec_usu_hogar`"* into a reproducible artifact: markdown report +
optional runnable Python script. SQL stays in **DuckDB**, plots are
rendered **outside the brain** (the script is saved for the user to run).

> **Table-name resolution.** Users (and the PDF) may say
> `gold.indec_usu_hogar`. The actual warehouse table is
> **`gold.indec_eph_usu_hogar`** (per `AGENTS.md` → INDEC EPH ingest
> contract and `./skills/ingest-indec-mercadolaboral`). Always resolve the
> real name with `information_schema` before any other SQL — never
> hard-code either form.

## Tooling surface (hard constraints — match `AGENTS.md`)

| Step | MCP tool | Purpose |
|------|----------|---------|
| Resolve & inspect | `duckdb_get_schema`, `duckdb_execute_query` | confirm table name, list columns, count rows |
| Aggregate | `duckdb_execute_query` | every analytical SELECT (one statement per call) |
| (optional) Catalog | `dagster_catalog_execute_query` | only if the metadata DB is configured on **dagster-mcp** — see `./skills/catalog-sql/SKILL.md` |
| Save artifacts | `write_file` (Deep Agents virtual FS) | markdown report + Python plot script under `reports/...` |

**Forbidden** in this skill: `database_execute_sql_query`, `ingest_csv`,
any `*_warehouse_*` legacy alias not in the runtime tool list, and any
attempt to open `/data/warehouse.duckdb` from Python (the warehouse file
lives in a Docker volume and is held by `duckdb-mcp` — see
`AGENTS.md` → *Warehouse file lock*).

## Workflow checklist

```
- [ ] 1. Resolve real table name + grain (years / quarters / row counts)
- [ ] 2. Pull column dictionary from silver (LEFT JOIN information_schema)
- [ ] 3. ASK the user for focus + window (single focused question — skip if both already given)
- [ ] 4. Build the analysis (SQL aggregates → markdown report; optional run.py for plots)
- [ ] 5. Save under reports/indec_eph_usu_hogar/<topic>/ via write_file and return a short summary
```

### 1. Resolve table + grain

Two `duckdb_execute_query` calls — milliseconds, prevents name/grain mistakes:

```sql
-- (a) confirm the gold table exists and pick the real name
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'gold'
  AND table_name LIKE '%usu_hogar%';
```

```sql
-- (b) grain — years × quarters × hogares únicos
SELECT
    ANO4,
    TRIMESTRE,
    COUNT(*)                                          AS rows,
    COUNT(DISTINCT CODUSU)                            AS viviendas,
    COUNT(DISTINCT CODUSU || '|' || NRO_HOGAR)        AS hogares
FROM gold.indec_eph_usu_hogar
GROUP BY 1, 2
ORDER BY 1, 2;
```

Natural primary key: **`(CODUSU, NRO_HOGAR, ANO4, TRIMESTRE)`** — one row
per surveyed hogar per quarter.

### 2. Column dictionary from silver

`silver.indec_mercado_laboral_variables` is the source of truth for column
meanings. Schema: `(id, campo, longitud, tipo, descripcion)`. Match
`campo` against `information_schema.columns.column_name` for the gold
table (case-sensitive — INDEC uses upper-case identifiers).

#### Canonical EPH columns (do not rename, do not invent)

INDEC microdata uses **fixed UPPER-CASE** identifiers. **Never** infer a
column from natural language; copy these names verbatim. If you need
something not on this list, run the `information_schema` query in step 1
**first**, do not guess.

| Concept | Correct column | Wrong names that will fail |
|---------|---------------|----------------------------|
| Año (4 dígitos)        | **`ANO4`**       | `year`, `anio`, `año`, `ANIO`, `ANO` |
| Trimestre (1..4)       | **`TRIMESTRE`**  | `quarter`, `q`, `trim`, `TRIM` |
| Región                 | **`REGION`**     | `region_id`, `id_region` |
| Aglomerado             | **`AGLOMERADO`** | `aglo`, `agl` |
| Vivienda (id muestral) | **`CODUSU`**     | `cod_usu`, `id_vivienda` |
| Hogar dentro vivienda  | **`NRO_HOGAR`**  | `nro`, `hogar_id` |
| Pesos (conteos)        | **`PONDERA`**    | `ponderador`, `weight`, `peso` |
| Pesos (ingresos)       | **`PONDIH`**     | `ponderador_ingreso`, `pondii` |
| Ingreso total familiar | **`ITF`**        | `ingreso_total`, `total_ingreso` |
| Ingreso per cápita     | **`IPCF`**       | `ingreso_pc`, `pcf` |
| Decil de ITF           | **`DECIFR`**     | `decil_itf`, `decil` |
| Decil de IPCF          | **`DECCFR`**     | `decil_ipcf` |

> If `information_schema` reports a different name in this warehouse, the
> warehouse wins — but the SQL filter for time **is `WHERE ANO4 = <Y>
> AND TRIMESTRE = <T>`** for every quarter loaded by
> `./skills/ingest-indec-mercadolaboral/SKILL.md`.

```sql
WITH cols AS (
    SELECT column_name, ordinal_position, data_type
    FROM information_schema.columns
    WHERE table_schema = 'gold' AND table_name = 'indec_eph_usu_hogar'
)
SELECT
    c.ordinal_position AS pos,
    c.column_name      AS campo,
    c.data_type        AS tipo_sql,
    s.tipo             AS tipo_eph,
    s.longitud,
    s.descripcion
FROM cols c
LEFT JOIN silver.indec_mercado_laboral_variables s
       ON s.campo = c.column_name
ORDER BY c.ordinal_position;
```

> **If silver coverage is partial** (the `variables_eph` Dagster asset
> processes the PDF page-by-page and may not yet cover every column),
> proceed with what is available and call out coverage in the
> *Limitaciones* section of the report. Do **not** invent descriptions
> for missing columns; keep their technical name and reference
> `EPH_registro_*.pdf` as the upstream source. Suggest (do not run
> without asking) re-materializing `indec_mercado_laboral_variables_job`
> via `dagster_*` tools to extend coverage.

### 3. Ask one focused question

The brain has no menu widget. **Ask one question, plain text, in the
user's language**. Confirm focus and window in a single turn so step 4
runs without further interruption.

**Skip the question entirely** when the user already said both — e.g.
*"hogares por región en T3-2025"* → focus=`regional`, window=`(2025, 3)`,
proceed.

Canonical analysis families and the columns they touch (use to seed the
question — never re-explain all of them; pick the 3–4 most relevant for
the user's wording):

| id | Análisis | Variables clave |
|----|----------|-----------------|
| `regional` | Distribución de hogares por región / aglomerado | `REGION`, `AGLOMERADO`, `MAS_500`, `PONDERA` |
| `ingresos` | Ingreso total familiar (ITF) y per cápita (IPCF), deciles, p10/p50/p90 | `ITF`, `IPCF`, `DECIFR`, `DECCFR`, `PONDIH` |
| `vivienda` | Calidad de vivienda y hacinamiento | `IV1`, `IV3`–`IV12_*`, `IX_TOT`, `IX_MEN10` |
| `tenencia` | Régimen de tenencia y servicios básicos | `II7`, `IV6`–`IV11` |
| `composicion` | Tamaño y composición demográfica del hogar | `IX_TOT`, `IX_MEN10`, `IX_MAYEQ10` |
| `serie` | Evolución trimestral de cualquiera de los anteriores | `ANO4`, `TRIMESTRE` + variable elegida |
| `cruces` | Cruces personalizados (ej. ingreso × región × tenencia) | combinación |

Question template (Spanish — switch to English if the user wrote in
English):

> Antes de seguir necesito dos cosas: (a) **foco** del análisis — por
> ejemplo `regional` (hogares por región), `ingresos` (ITF/IPCF deciles),
> `vivienda`, `tenencia`, `composicion`, `serie` (evolución trimestral)
> u otro; y (b) **ventana** — último trimestre disponible, año completo
> más reciente, o todos los trimestres cargados. ¿Cuál preferís?

### 4. Build the analysis

**Computation rule:** push every aggregation into DuckDB via
`duckdb_execute_query`. Keep result sets small (the MCP truncates large
ones — see `AGENTS.md` → *Result sets from tools may be truncated*).
Never `SELECT *` against this 96k-row × ~95-column table.

**Sample weights — non-negotiable.** EPH is a complex sample.

- Conteos / shares de hogares → `SUM(PONDERA)`
- Medias por hogar (variables monetarias) → `SUM(var * PONDERA) / SUM(PONDERA)`
- Medianas / deciles de ingreso per cápita → use `PONDIH` instead of `PONDERA` (or use the `DECCFR` field that INDEC already produces)

**Numeric casting — non-negotiable.** INDEC TXTs ingest with mixed
numeric / empty / placeholder values, so `read_csv_auto` frequently
stores monetary and many `IV*` / `II*` columns as **`VARCHAR`**.
**Every** numeric aggregate (`AVG`, `SUM`, `quantile_cont`, arithmetic)
**must** wrap the column in **`TRY_CAST(<col> AS DOUBLE)`** (or
`::DOUBLE` after you have proved the column is clean). Use `TRY_CAST` —
**not `CAST`** — so non-numeric placeholders become `NULL` instead of
aborting the query with `BinderException` or `Conversion Error`. Apply
the same rule to the weight (`TRY_CAST(PONDERA AS DOUBLE)`,
`TRY_CAST(PONDIH AS DOUBLE)`); INDEC weights are integers but ingest
sometimes still loads them as `VARCHAR`. Verify once with:

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'gold'
  AND table_name = 'indec_eph_usu_hogar'
  AND column_name IN ('ITF','IPCF','PONDERA','PONDIH','DECIFR','DECCFR');
```

and document the actual types in the report's *Método* section.

**Filtering rule.** Always `WHERE ANO4 = <Y> AND TRIMESTRE = <T>` unless
the focus is `serie`.

**One statement per call.** No semicolon-chained DDL/DML in a single
`duckdb_execute_query` invocation (consistent with the warehouse-lock
discipline in `AGENTS.md` and `./skills/ingest-indec-mercadolaboral`).

#### Reference aggregate — `regional` focus, T3-2025

```sql
SELECT
    REGION,
    SUM(TRY_CAST(PONDERA AS DOUBLE))                                  AS hogares_pond,
    SUM(TRY_CAST(PONDERA AS DOUBLE)) * 1.0
        / SUM(SUM(TRY_CAST(PONDERA AS DOUBLE))) OVER ()              AS share
FROM gold.indec_eph_usu_hogar
WHERE ANO4 = 2025 AND TRIMESTRE = 3
GROUP BY REGION
ORDER BY hogares_pond DESC;
```

#### Reference aggregate — `ingresos` focus, deciles ITF

```sql
-- mediana / p10 / p90 ponderados por PONDIH (per cápita: usar IPCF)
WITH base AS (
    SELECT
        TRY_CAST(ITF    AS DOUBLE) AS itf,
        TRY_CAST(PONDIH AS DOUBLE) AS w
    FROM gold.indec_eph_usu_hogar
    WHERE ANO4 = 2025 AND TRIMESTRE = 3
)
SELECT
    quantile_cont(itf, 0.10 USING w)  AS itf_p10,
    quantile_cont(itf, 0.50 USING w)  AS itf_p50,
    quantile_cont(itf, 0.90 USING w)  AS itf_p90,
    SUM(itf * w) / NULLIF(SUM(w), 0)  AS itf_mean
FROM base
WHERE itf IS NOT NULL AND itf >= 0 AND w IS NOT NULL;
```

> If `quantile_cont(... USING <weight>)` is not supported in this
> DuckDB version, fall back to `DECIFR` (INDEC-published deciles of ITF)
> or `DECCFR` (deciles of IPCF) and weight by `PONDIH`. Document the
> fallback in *Método*.

#### Reference aggregate — `serie` focus

```sql
WITH base AS (
    SELECT
        ANO4, TRIMESTRE,
        TRY_CAST(PONDERA AS DOUBLE) AS w_pers,
        TRY_CAST(PONDIH  AS DOUBLE) AS w_ing,
        TRY_CAST(IPCF    AS DOUBLE) AS ipcf,
        IV1
    FROM gold.indec_eph_usu_hogar
)
SELECT
    ANO4, TRIMESTRE,
    SUM(w_pers)                                                       AS hogares_pond,
    SUM(CAST(IV1 IN ('1','2') AS DOUBLE) * w_pers)
        / NULLIF(SUM(w_pers), 0)                                      AS share_casa_dpto,
    SUM(ipcf * w_ing) / NULLIF(SUM(w_ing), 0)                         AS ipcf_mean
FROM base
GROUP BY 1, 2
ORDER BY 1, 2;
```

> Note the `IV1 IN ('1','2')` (string literals): when columns load as
> `VARCHAR`, comparisons must use string literals — `IV1 IN (1,2)` will
> raise `Conversion Error`. After verifying types per the type-check
> query above, switch to integer literals only if `IV1` is `INTEGER`.

### 5. Save artifacts

Use `write_file` (Deep Agents virtual FS — rooted at the project) to
persist the report. **Layout:**

```
reports/indec_eph_usu_hogar/<topic>/
├── README.md      # exec summary, method, findings, SQL, limitations
├── data/<q>.csv   # one CSV per aggregate (the row data behind each plot)
└── run.py         # OPTIONAL — pandas + matplotlib script the user can run
```

`<topic>` examples: `regional-3T2025`, `ingresos-deciles-3T2025`,
`serie-ipcf-2025`. Use `[a-z0-9_-]+` only (consistent with `AGENTS.md`
identifier discipline).

**`README.md` template** (concise — match the `AGENTS.md` "Deliverables" voice):

````markdown
# EPH hogares — <topic> (<period>)

## Resumen ejecutivo
<1 paragraph>

## Método
- Tabla: `gold.indec_eph_usu_hogar` (rows=<n>, hogares=<n>, ventana=<...>)
- Pesos: `PONDERA` para conteos, `PONDIH` para ingresos per cápita
- Diccionario: `silver.indec_mercado_laboral_variables` (cobertura: <k>/<N> columnas; gaps: <list>)

## Hallazgos
- bullet 1 (con número y unidad)
- bullet 2

## SQL
```sql
<exact aggregate query>
```

## Limitaciones
- silver dictionary cobertura parcial — variables sin descripción se etiquetaron con su nombre técnico
- <other>
````

**`run.py` skeleton** (only emit when the user wants plots — otherwise
the markdown report is enough). Do **not** import `duckdb`; this script
runs against the CSVs the brain already saved next to it:

```python
"""Plot EPH hogar aggregates pre-computed by duckdb_execute_query."""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
DATA = HERE / "data"
PLOTS = HERE / "plots"; PLOTS.mkdir(exist_ok=True)

REGION_LABELS = {1:"GBA", 40:"NOA", 41:"NEA", 42:"Cuyo", 43:"Pampeana", 44:"Patagonia"}
TRIM_LABELS   = {1:"1T", 2:"2T", 3:"3T", 4:"4T"}

def regional_share():
    df = pd.read_csv(DATA / "regional.csv")
    df["region"] = df["REGION"].map(REGION_LABELS).fillna(df["REGION"].astype(str))
    ax = df.plot.bar(x="region", y="share", legend=False)
    ax.set_ylabel("Share of households (PONDERA-weighted)")
    ax.set_title("EPH — distribución de hogares por región")
    plt.tight_layout()
    plt.savefig(PLOTS / "regional_share.png", dpi=150)

if __name__ == "__main__":
    regional_share()
```

Setup snippet to include in `README.md` so the user can run it:

```bash
uv venv && source .venv/bin/activate
uv pip install pandas matplotlib
python reports/indec_eph_usu_hogar/<topic>/run.py
```

## Reglas duras

1. **Nunca** `SELECT *` sobre `gold.indec_eph_usu_hogar`.
2. **Siempre** ponderá con `PONDERA` (conteos) o `PONDIH` (per cápita).
3. **Siempre** filtrá por `(ANO4, TRIMESTRE)` salvo `serie`.
4. **Una sola sentencia** por `duckdb_execute_query` (no chains).
5. **Identificadores SQL** sin comillas, `[a-zA-Z0-9_]+` (consistente con `AGENTS.md`).
6. **Idioma de respuesta** = idioma del usuario (default español).
7. **No abras** `/data/warehouse.duckdb` desde Python (lock conflict —
   ese archivo lo tiene `duckdb-mcp`).
8. **Siempre `TRY_CAST(<col> AS DOUBLE)`** para `ITF`, `IPCF`, `PONDERA`,
   `PONDIH` (y otras columnas monetarias / numéricas) antes de `AVG`,
   `SUM`, `quantile_cont` o aritmética: el ingest INDEC deja muchas como
   `VARCHAR`. Verificá los tipos vía `information_schema.columns` y
   declaralos en *Método*.

## Anti-patrones

| Wrong | Why |
|-------|-----|
| `COUNT(*) GROUP BY REGION` sin `PONDERA` | EPH es muestra ponderada; conteos crudos no representan la población |
| `SELECT * FROM gold.indec_eph_usu_hogar LIMIT 1000` "para ver datos" | usa `information_schema.columns` + el JOIN del paso 2 |
| `gold.indec_usu_hogar` (sin `eph_`) hard-codeado | siempre resolvé el nombre real en el paso 1 |
| `WHERE year = 2025` o `WHERE anio = 2025` | la columna es **`ANO4`** (UPPER); `year`/`anio` no existen |
| `WHERE quarter = 3` o `WHERE q = 3` | la columna es **`TRIMESTRE`** (1..4) |
| `AVG(IPCF)` / `SUM(ITF * PONDIH)` sin cast | INDEC ingest deja columnas monetarias como `VARCHAR`; usá `TRY_CAST(<col> AS DOUBLE)` |
| `CAST(IPCF AS DOUBLE)` (sin `TRY_`) sobre toda la tabla | placeholders no numéricos rompen la query; `TRY_CAST` los manda a `NULL` |
| `IV1 IN (1, 2)` cuando `IV1` es `VARCHAR` | usá `IV1 IN ('1','2')` o castea explícito; nunca asumas el tipo |
| Dos `CREATE TABLE` o `INSERT` chained en un `duckdb_execute_query` | rompe el contrato de "una sentencia por call" |
| Pedir foco **y** ventana en preguntas separadas | una sola pregunta enfocada — no fragmentes el turno |
| Inventar descripciones para columnas no cubiertas en silver | dejá el nombre técnico y declaralo en *Limitaciones* |

## Códigos INDEC útiles

```text
REGION : 1=GBA, 40=NOA, 41=NEA, 42=Cuyo, 43=Pampeana, 44=Patagonia
TRIMESTRE : 1..4 (1T..4T)
IV1 (tipo de vivienda), II7 (régimen de tenencia), MAS_500 (S/N) — leer descripcion desde silver
```

## Cobertura de silver

`variables_eph` (Dagster bronze) procesa el PDF
`EPH_registro_*.pdf` página por página y
`silver_indec_mercado_laboral_variables` lo aplana. Cobertura típica
inicial: solo las primeras páginas (cabecera + ID variables) se
materializan tras la primera corrida. Si la consulta de cobertura del
paso 2 devuelve pocas filas:

1. **No bloquees** el análisis. Ejecutá el LEFT JOIN y reportá la cobertura.
2. Para variables comunes (`ITF`, `IPCF`, `REGION`, `ANO4`, `TRIMESTRE`,
   `PONDERA`, `PONDIH`) usá las definiciones del INDEC EPH publicadas en
   `EPH_registro_*.pdf` sin inventar.
3. Sugerí (no ejecutes sin pedirlo) re-materializar
   `indec_mercado_laboral_variables_job` via los `dagster_*` tools para
   ampliar cobertura.

## Relación con otras skills

- **`./skills/ingest-indec-mercadolaboral/SKILL.md`** — origen de los datos en `gold.indec_eph_usu_hogar`. Esta skill **lee**, no ingesta.
- **`./skills/extract-variables-pdf/SKILL.md`** — pipeline upstream que llena `silver.indec_mercado_laboral_variables`.
- **No** mezcles esta skill con `gold.indec_eph_usu_individual` (microdatos de personas) — ese análisis tiene grano y pesos distintos.
