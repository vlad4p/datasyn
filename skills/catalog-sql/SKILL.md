---
name: catalog-sql
description: >-
  OpenMetadata-style catalog operations using catalog-mcp generic tools
  (get_schema, execute_query): list/search datasets, read by FQN, upsert
  entity_json, refresh tag_usage and entity_relationship. Use when the brain
  must query or mutate the PostgreSQL catalog without bespoke MCP tools.
---

# Catalog SQL (via `catalog_*` MCP)

The catalog MCP server registers **`get_schema`** and **`execute_query`**. With `mcp.json` server key **`catalog`**, LangChain exposes them as **`catalog_get_schema`** and **`catalog_execute_query`**.

## Tables (see `catalog_get_schema`)

- **`dataset_entity`**: `id`, `fully_qualified_name`, `entity_json` (JSONB), timestamps. `search_tsv` is **generated** from FQN + name fields.
- **`tag_usage`**: `target_id` → `dataset_entity.id`, `tag_fqn`, `source` (0=classification, 1=glossary).
- **`entity_relationship`**: lineage edges `from_id`, `to_id`, `relation` ∈ (`upstream`,`downstream`).

## List datasets (summary)

Use **`catalog_execute_query`** with SQL equivalent to `agent.utils.catalog_sql.build_list_datasets_sql` (filters optional):

```sql
SELECT id, entity_json
FROM dataset_entity
WHERE ('' = '' OR entity_json->'service'->>'name' ILIKE '%' || '' || '%')
  AND ('' = '' OR entity_json->'database'->>'name' = '')
  AND ('' = '' OR entity_json->'schema'->>'name' = '')
ORDER BY updated_at DESC
LIMIT 50;
```

Escape single quotes in user-supplied filter strings (`''`).

## Get one dataset by FQN

```sql
SELECT id, entity_json
FROM dataset_entity
WHERE fully_qualified_name = 'duckdb-warehouse.main.raw.my_table'
LIMIT 1;
```

## Full-text search

```sql
SELECT id, entity_json,
       ts_rank_cd(search_tsv, plainto_tsquery('simple', 'my term')) AS rank
FROM dataset_entity
WHERE search_tsv @@ plainto_tsquery('simple', 'my term')
ORDER BY rank DESC, updated_at DESC
LIMIT 20;
```

## Upsert `entity_json`

Prefer **`INSERT … ON CONFLICT (fully_qualified_name) DO UPDATE`** so you merge lineage from a prior **`SELECT`** in the brain before writing.

Minimal shape inside `entity_json`: `fullyQualifiedName`, `name`, `displayName`, `description`, `tableType`, `service`, `database`, `schema`, `columns`, `tags`, `owners`, `glossaryTerms`, `upstreamLineage`, `downstreamLineage`, `sourceUrl`, `customProperties`, `createdAt`, `updatedAt`.

On **update**, re-read **`upstreamLineage` / `downstreamLineage`** from the existing row if you must preserve them while changing columns.

## Refresh `tag_usage`

After changing `entity_json.tags`, replace denormalized rows:

```sql
DELETE FROM tag_usage WHERE target_id = <id>;
INSERT INTO tag_usage (target_id, tag_fqn, source) VALUES (<id>, 'Tier.PII', 0);
-- repeat INSERT per tag dict (tagFQN / tagFqn + source)
```

## Refresh `entity_relationship` (lineage)

For dataset id **`D`** (target row):

1. `DELETE FROM entity_relationship WHERE (from_id = D OR to_id = D) AND relation IN ('upstream','downstream');`
2. For each upstream FQN, resolve `other_id` via `SELECT id FROM dataset_entity WHERE fully_qualified_name = '…'`, then:
   `INSERT INTO entity_relationship (from_id, to_id, from_entity, to_entity, relation) VALUES (other_id, D, 'dataset', 'dataset', 'upstream') ON CONFLICT DO NOTHING;`
3. Downstream: `VALUES (D, other_id, …, 'downstream')`.

Do not insert self-edges (`from_id = to_id`).

## Safety

`execute_query` rejects DDL and multi-statements. Use **one statement per call**; chain steps as **separate** tool invocations.

## Helpers in code

- **`agent.utils.catalog_sql`**: `build_list_datasets_sql`, `build_get_dataset_sql`, `build_search_datasets_sql` for typed SQL from the **brain** HTTP path (`GET /catalog/datasets`).
