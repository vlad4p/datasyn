---
name: graph-ingest
description: >-
  Build graph tables (vertices & edges) from entity-link tables in DuckDB
  using SQL via MCP only. Creates grafo_vertices, grafo_edges, grafo_edges_agg.
  Use when the user asks to create a graph, network, or co-occurrence model
  from entities and their relationships.
---

# Graph ingest (skill — SQL via MCP only)

Build a property graph from entity-link tables already in DuckDB. Runs entirely
via SQL through MCP (`uv run python scripts/python/db.py run-sql "SQL..."`).

## Prerequisites

- `entidades.entidades` table with `id`, `nombre`, `tipo` columns
- `entidad_vinculos` table with `entidad_id`, `aviso_id`, `rol` columns
- Or any analogous entity + relationship tables

## Workflow

1. **Verify sources** — `SELECT COUNT(*) FROM entidades.entidades`, `SELECT COUNT(*) FROM entidad_vinculos`
2. **Create vertex table** — one row per entity (node)
3. **Create edge tables** — co-occurrence of entities in the same event/aviso
4. **Validate** — vertex/edge counts, check for isolated nodes

## SQL templates

### Step 1: Create vertex table

```sql
CREATE OR REPLACE TABLE grafo_vertices AS
SELECT
    id AS vertex_id,
    nombre AS label,
    tipo AS entity_type
FROM entidades.entidades;
```

### Step 2: Create raw edge table (co-occurrence)

Two entities share an edge if they appear in the same aviso:

```sql
CREATE OR REPLACE TABLE grafo_edges AS
SELECT
    a.entidad_id AS source_id,
    b.entidad_id AS target_id,
    a.aviso_id,
    'co_occurrence' AS edge_type,
    COUNT(*) AS weight
FROM entidad_vinculos a
JOIN entidad_vinculos b
  ON a.aviso_id = b.aviso_id
 AND a.entidad_id < b.entidad_id
GROUP BY a.entidad_id, b.entidad_id, a.aviso_id;
```

### Step 3: Aggregate edge table (deduplicate pairs)

```sql
CREATE OR REPLACE TABLE grafo_edges_agg AS
SELECT
    source_id,
    target_id,
    COUNT(*) AS co_occurrences,
    COUNT(DISTINCT aviso_id) AS shared_avisos
FROM grafo_edges
GROUP BY source_id, target_id;
```

### Step 4: Validate

```sql
-- Counts
SELECT
    (SELECT COUNT(*) FROM grafo_vertices) AS vertices,
    (SELECT COUNT(*) FROM grafo_edges) AS raw_edges,
    (SELECT COUNT(*) FROM grafo_edges_agg) AS unique_pairs;

-- Isolated vertices
SELECT v.*
FROM grafo_vertices v
LEFT JOIN grafo_edges_agg e
  ON v.vertex_id = e.source_id OR v.vertex_id = e.target_id
WHERE e.source_id IS NULL;
```

## Entity extraction (prerequisite)

The graph tables require two source tables: `entidades.entidades` (nodes) and
`entidad_vinculos` (edges). These **must** exist before running graph ingest.

### When entities already exist

Verify with MCP:

```sql
SELECT COUNT(*) FROM entidades.entidades;
SELECT COUNT(*) FROM entidad_vinculos;
```

### When entities don't exist yet

Entity extraction is **domain-specific** — every data source needs its own logic.
There is no universal entity extractor.

**For each use case, create a custom extraction script** under
`scripts/python/` using the **`create-python-script`** skill. The script must:

1. Read the source data (landing files, scraped data, or existing DuckDB tables)
2. Extract unique entities (people, companies, organizations, etc.) → insert into `entidades.entidades`
3. Create relationships (who links to what, in which context) → insert into `entidad_vinculos`
4. Deduplicate by `(nombre, tipo)`

#### Schema reference

```sql
-- entidades.entidades
id     INTEGER PRIMARY KEY
nombre VARCHAR NOT NULL
tipo   VARCHAR NOT NULL  -- 'empresa', 'persona', 'lugar', etc.

-- entidad_vinculos
entidad_id  INTEGER NOT NULL      -- FK → entidades.entidades
aviso_id     VARCHAR NOT NULL     -- context/event ID (use your own column name)
rol         VARCHAR NOT NULL      -- 'socio', 'presidente', 'autor', etc.
PRIMARY KEY (entidad_id, aviso_id)
```

#### Example: Boletín Oficial

The existing script `scripts/python/extraer_entidades.py` extracts companies and
socios from the Argentine government gazette. It is **only useful for that data
source** — it uses regex patterns tailored to Spanish legal text.

```bash
uv run python scripts/python/extraer_entidades.py
```

For any other data source, build a new script with `create-python-script` skill.

### Custom extraction template

```python
# scripts/python/extraer_mis_entidades.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts/python").resolve()))
import db

con = db.connect()
try:
    # 1. Read source data
    rows = con.sql("SELECT id, titulo, contenido FROM mi_tabla").fetchall()

    # 2. Extract entities (domain-specific logic)
    for row in rows:
        # ... parse names, detect types, etc.
        # con.execute("INSERT INTO entidades.entidades ...")
        pass

    # 3. Validate
    con.sql("SELECT tipo, COUNT(*) FROM entidades.entidades GROUP BY tipo").show()
finally:
    con.close()
```

## Notes

- Co-occurrence edges form cliques within each aviso (every entity in the aviso connects to every other)
- The `a.entidad_id < b.entidad_id` condition avoids self-loops and duplicate undirected edges
- Edge weight = number of shared avisos between two entities
- Isolated vertices = entities with no detected relationships
