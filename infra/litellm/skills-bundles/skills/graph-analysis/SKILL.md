---
name: graph-analysis
description: >-
  Analyze property graphs (vertices & edges) in DuckDB using SQL via MCP only.
  Computes centrality, degree distribution, density, communities,
  co-occurrence networks. Produces markdown reports under reports/.
  Use for network analysis, connection mapping, community detection,
  or influence metrics from entity graphs.
---

# Graph analysis (skill — SQL via MCP only)

Analyze graph tables (`grafo_vertices`, `grafo_edges`, `grafo_edges_agg`) using
pure SQL through MCP. No graph extensions required. Write findings to `reports/`.

## Prerequisites

- Graph tables exist: `grafo_vertices`, `grafo_edges`, `grafo_edges_agg`
- If not, use skill `graph-ingest` first
- Output: `reports/` directory

## Workflow

1. **Profile the graph** — vertex/edge counts, density, degree distribution
2. **Rank by centrality** — find most connected nodes
3. **Detect communities** — multi-entity links, shared entities across companies
4. **Draft report** — markdown with findings
5. **Save** — `reports/grafo_{YYYYMMDD}.md`

---

## Core queries

### Graph profile

```sql
-- Global metrics
SELECT
    (SELECT COUNT(*) FROM grafo_vertices) AS vertices,
    (SELECT COUNT(*) FROM grafo_edges) AS raw_edges,
    (SELECT COUNT(*) FROM grafo_edges_agg) AS unique_pairs;

-- Density (undirected)
WITH s AS (
    SELECT
        COUNT(*) AS v,
        COUNT(*) AS e
    FROM grafo_edges_agg
)
SELECT ROUND(2.0 * e / (v * (v - 1)), 4) AS density FROM s;

-- Connected vs isolated
SELECT
    COUNT(*) FILTER (WHERE e.source_id IS NOT NULL) AS connected,
    COUNT(*) FILTER (WHERE e.source_id IS NULL) AS isolated
FROM grafo_vertices v
LEFT JOIN grafo_edges_agg e
  ON v.vertex_id = e.source_id OR v.vertex_id = e.target_id;
```

### Degree distribution

```sql
WITH degree AS (
    SELECT v.vertex_id,
           COUNT(e.source_id) + COUNT(e.target_id) AS d
    FROM grafo_vertices v
    LEFT JOIN grafo_edges_agg e
      ON v.vertex_id = e.source_id OR v.vertex_id = e.target_id
    GROUP BY v.vertex_id
)
SELECT
    CASE
        WHEN d = 0 THEN '0 (isolated)'
        WHEN d BETWEEN 1 AND 3 THEN '1-3'
        WHEN d BETWEEN 4 AND 10 THEN '4-10'
        WHEN d BETWEEN 11 AND 20 THEN '11-20'
        ELSE '20+'
    END AS degree_range,
    COUNT(*) AS vertices,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) AS pct
FROM degree
GROUP BY 1
ORDER BY MIN(d);
```

### Top entities by degree centrality

```sql
SELECT
    v.label,
    v.entity_type,
    COUNT(DISTINCT e.source_id) + COUNT(DISTINCT e.target_id) AS degree
FROM grafo_vertices v
INNER JOIN grafo_edges_agg e
  ON v.vertex_id = e.source_id OR v.vertex_id = e.target_id
GROUP BY v.vertex_id, v.label, v.entity_type
ORDER BY degree DESC
LIMIT 20;
```

### Community detection — shared entities across companies

```sql
-- People who appear in multiple companies
SELECT
    e.nombre AS persona,
    COUNT(DISTINCT ev2.entidad_id) AS empresas_count,
    LIST(DISTINCT ee.nombre ORDER BY ee.nombre) AS empresas
FROM entidad_vinculos ev
JOIN entidades.entidades e
  ON e.id = ev.entidad_id AND e.tipo = 'persona'
JOIN entidad_vinculos ev2
  ON ev.aviso_id = ev2.aviso_id
 AND ev2.entidad_id != ev.entidad_id
JOIN entidades.entidades ee
  ON ee.id = ev2.entidad_id AND ee.tipo = 'empresa'
GROUP BY e.id, e.nombre
HAVING COUNT(DISTINCT ev2.entidad_id) >= 2
ORDER BY empresas_count DESC;
```

### Companies linked by shared people

```sql
WITH persona_empresa AS (
    SELECT DISTINCT
        ev2.entidad_id AS empresa_id,
        ev1.entidad_id AS persona_id
    FROM entidad_vinculos ev1
    JOIN entidad_vinculos ev2
      ON ev1.aviso_id = ev2.aviso_id
    JOIN entidades.entidades pe
      ON pe.id = ev1.entidad_id AND pe.tipo = 'persona'
    JOIN entidades.entidades em
      ON em.id = ev2.entidad_id AND em.tipo = 'empresa'
)
SELECT
    e1.nombre AS empresa_a,
    e2.nombre AS empresa_b,
    COUNT(*) AS shared_people
FROM persona_empresa a
JOIN persona_empresa b
  ON a.persona_id = b.persona_id
 AND a.empresa_id < b.empresa_id
JOIN entidades.entidades e1 ON e1.id = a.empresa_id
JOIN entidades.entidades e2 ON e2.id = b.empresa_id
GROUP BY e1.nombre, e2.nombre
HAVING COUNT(*) >= 2
ORDER BY shared_people DESC;
```

---

## Report template (`.md`)

```markdown
# Análisis de Grafos — {description}

Generated: {date}
Source tables: grafo_vertices ({n} nodes), grafo_edges ({m} edges)

## Graph structure
- Vertices: ...
- Edges: ...
- Density: ...
- Connected: ... (isolated: ...)

## Degree distribution
[table]

## Top entities by centrality
[table]

## Communities / Shared entities
[findings]

## Findings
- ...

## Limits
- What was NOT checked
- False positives in extraction
- SQL-only (no native graph algorithms)
```
