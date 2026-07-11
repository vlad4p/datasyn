---
name: lineage-mcp-app
description: >-
  Build or extend the MCP Apps / MCP-UI lineage view for Quack sync
  (ui://datasyn/lineage). Use when the user asks about sync lineage graph,
  MCP-UI resources, or the Sync & Lineage panel.
---

# Lineage MCP App (ui://datasyn/lineage)

## When to use

- Explain or extend the **Sync & Lineage** UI panel.
- Serve / debug the MCP Apps **UIResource** at `ui://datasyn/lineage`.
- Add nodes/edges beyond `medallion.sync_registry`.

## Protocol shape (MCP Apps)

Tools/resources declare UI via `_meta.ui.resourceUri`. The host renders HTML in a sandboxed iframe.

Datasyn brain endpoint:

- `GET /lineage/ui-resource` →

```json
{
  "status": "ok",
  "type": "resource",
  "resource": {
    "uri": "ui://datasyn/lineage",
    "mimeType": "text/html",
    "text": "<!DOCTYPE html>…vis-network…"
  },
  "_meta": { "ui": { "resourceUri": "ui://datasyn/lineage" } }
}
```

Implementation: [`agent/sync/quack_sync.py`](../../agent/sync/quack_sync.py) → `build_lineage_ui_resource()`.

## Graph model

| Node group | Meaning |
|------------|---------|
| `source` | External Quack instance (sync source name) |
| `external` | Table FQN on the external (`source_fqn`) |
| `main` | Table FQN on the main warehouse (`target_fqn`) |

Edges: instance → external table → main table (label = last sync `status`).

Data source: latest distinct `(source_name, source_fqn, target_fqn)` from `medallion.sync_registry` (via `GET /sync/status` / `sync_status()`).

## UI host

[`ui/src/components/SyncLineagePanel.tsx`](../../ui/src/components/SyncLineagePanel.tsx):

1. **Sync now** → `POST /sync/run`
2. Table of registry rows → `GET /sync/status`
3. Lineage graph → `GET /lineage/ui-resource`
   - Prefer `@mcp-ui/client` `UIResourceRenderer`
   - Fallback: sandboxed `<iframe sandbox="allow-scripts" srcDoc={html}>`

## Extending

1. Enrich `build_lineage_ui_resource()` with catalog/Dagster lineage if needed (merge `/catalog/datasets` edges carefully; keep sync edges distinct).
2. Keep HTML self-contained (CDN vis-network is OK); avoid leaking secrets into the iframe.
3. Do not call MCP directly from the browser — always proxy through the brain.

## Related skill

- [`sync-duckdb-quack`](../sync-duckdb-quack/SKILL.md) — how tables get into `sync_registry`.
