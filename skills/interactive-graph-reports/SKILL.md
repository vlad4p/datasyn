# Skill: Interactive Graph Reports

**Purpose:** Generate interactive, HTML-based graph visualizations with statistics and analytics from structured node/edge data.

**Domain:** Data visualization, network analysis, knowledge graph exploration  
**Output format:** HTML (vis.js + React) + Markdown analytics reports  
**Data requirement:** Nodes (entities), edges (relationships), optional node/edge attributes

---

## When to Use This Skill

✅ **Use this skill when you have:**
- Network or graph data (nodes + edges)
- Entity-relationship datasets
- Hierarchical or interconnected data structures
- Need for interactive exploration + static analytics

❌ **Do NOT use when:**
- Data is purely tabular (use `statistical-report`)
- Only need simple charts (use Chart.js directly)
- Graph is too large (>10,000 nodes; requires clustering)

**Example scenarios:**
- Organization networks (employees, departments, connections)
- Knowledge graphs (concepts, relationships)
- Supply chains (organizations, contracts, transactions)
- Social networks (users, followers, interactions)
- Procurement networks (agencies, contractors, awards)

---

## Input Data Structure

### Required Format

Nodes JSON:
```json
[
  {
    "id": 1,
    "label": "Node Name",
    "tipo": "category_name"
  },
  ...
]
```

Edges JSON:
```json
[
  {
    "from": 1,
    "to": 2,
    "type": "relationship_type",
    "peso": 0.5,
    "metadata": "optional_field"
  },
  ...
]
```

### Complete Example

**nodes.json:**
```json
[
  {"id": 1, "label": "Ministerio A", "tipo": "organismo", "color": "#667eea"},
  {"id": 101, "label": "Contractor X", "tipo": "adjudicatario", "cuit": "20-12345678-9"},
  {"id": 102, "label": "Contractor Y", "tipo": "adjudicatario", "cuit": "30-87654321-0"}
]
```

**edges.json:**
```json
[
  {"from": 1, "to": 101, "type": "ADJUDICA_A", "peso": 50000, "fecha": "2026-06-01"},
  {"from": 1, "to": 102, "type": "ADJUDICA_A", "peso": 30000, "fecha": "2026-06-02"}
]
```

---

## Step-by-Step Usage

### Step 1: Export Data from DuckDB

```sql
-- Export organismos (nodes)
SELECT 
  organismo_id AS id,
  nombre AS label,
  'organismo' AS tipo
FROM silver.contrataciones_organismos;

-- Export adjudicatarios (nodes)
SELECT 
  100 + adjudicatario_id AS id,
  nombre AS label,
  'adjudicatario' AS tipo,
  cuit
FROM silver.contrataciones_adjudicatarios;

-- Export edges
SELECT 
  source_id AS 'from',
  target_id AS 'to',
  edge_type AS 'type',
  monto AS peso,
  boletin_fecha AS fecha
FROM silver.contrataciones_edges;
```

Save to JSON files:
- `nodes.json`
- `edges.json`

### Step 2: Generate Graph Data File

Use Python to combine nodes/edges into single JSON:

```python
import json

with open('nodes.json') as f:
    nodes = json.load(f)

with open('edges.json') as f:
    edges = json.load(f)

# Calculate stats
stats = {
    "total_nodes": len(nodes),
    "total_edges": len(edges),
    "node_types": {},
    "edge_types": {}
}

for node in nodes:
    tipo = node.get('tipo', 'unknown')
    stats['node_types'][tipo] = stats['node_types'].get(tipo, 0) + 1

for edge in edges:
    edge_type = edge.get('type', 'unknown')
    stats['edge_types'][edge_type] = stats['edge_types'].get(edge_type, 0) + 1

data = {
    "nodes": nodes,
    "edges": edges,
    "estadisticas": stats
}

with open('grafo.json', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"✅ Generated grafo.json with {len(nodes)} nodes, {len(edges)} edges")
```

### Step 3: Generate Interactive HTML Report

Create `grafo_interactivo.html` with:
- **vis.js** for network rendering
- **React** for UI controls
- **Controls:** search, filter, zoom, node details

```html
<!DOCTYPE html>
<html>
<head>
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body>
    <div id="network" style="width: 100%; height: 100vh;"></div>
    
    <script>
        fetch('grafo.json')
            .then(r => r.json())
            .then(data => {
                const { nodes: nodesData, edges: edgesData } = data;
                
                // Map to vis.js format
                const nodes = new vis.DataSet(
                    nodesData.map(n => ({
                        id: n.id,
                        label: n.label,
                        title: n.label,
                        color: n.tipo === 'organismo' ? '#667eea' : '#764ba2',
                        shape: n.tipo === 'organismo' ? 'box' : 'dot'
                    }))
                );
                
                const edges = new vis.DataSet(
                    edgesData.map(e => ({
                        from: e.from,
                        to: e.to,
                        label: e.type,
                        arrows: 'to'
                    }))
                );
                
                const container = document.getElementById('network');
                const options = {
                    physics: {
                        enabled: true,
                        barnesHut: {
                            gravitationalConstant: -26000,
                            centralGravity: 0.3,
                            springLength: 200
                        }
                    }
                };
                
                new vis.Network(container, { nodes, edges }, options);
            });
    </script>
</body>
</html>
```

### Step 4: Generate Analytics Report

Create `analytics.html` with Chart.js:

```html
<canvas id="nodeTypeChart"></canvas>
<script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
<script>
    fetch('grafo.json')
        .then(r => r.json())
        .then(data => {
            const stats = data.estadisticas;
            const ctx = document.getElementById('nodeTypeChart').getContext('2d');
            
            new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: Object.keys(stats.node_types),
                    datasets: [{
                        data: Object.values(stats.node_types),
                        backgroundColor: ['#667eea', '#764ba2', '#f093fb']
                    }]
                }
            });
        });
</script>
```

### Step 5: Generate Summary Markdown

Create `reporte_grafo.md` with:
- Key metrics (nodes, edges, density)
- Top nodes (highest degree)
- Edge type distribution
- Findings and insights

```markdown
# Graph Report

## Metrics
- **Nodes:** {{ total_nodes }}
- **Edges:** {{ total_edges }}
- **Density:** {{ density }}

## Top Nodes by Degree
{{ top_nodes_table }}

## Edge Type Distribution
{{ edge_type_chart }}
```

---

## Complete Example: Contrataciones

```bash
# 1. Export data from DuckDB
uv run python scripts/python/db.py run-sql << 'SQL'
  SELECT organismo_id, nombre FROM silver.contrataciones_organismos;
  SELECT adjudicatario_id, nombre FROM silver.contrataciones_adjudicatarios;
  SELECT source_id, target_id, edge_type FROM silver.contrataciones_edges;
SQL

# 2. Generate grafo.json with Python (see Step 2)
uv run python << 'PYTHON'
  import json
  # ... combine nodes/edges into grafo.json
PYTHON

# 3. Create HTML reports
# (see Step 3 for interactive HTML, Step 4 for analytics)

# 4. Open in browser
open grafo_interactivo.html
open analytics.html
```

---

## Configuration Options

### vis.js Physics Engine

```javascript
const options = {
  physics: {
    enabled: true,
    barnesHut: {
      gravitationalConstant: -26000,  // Attraction force
      centralGravity: 0.3,             // Pull to center
      springLength: 200,               // Ideal edge length
      damping: 0.9                     // Friction
    }
  }
};
```

**Presets:**
- **Tight clusters:** `gravitationalConstant: -50000`, `springLength: 100`
- **Sparse network:** `gravitationalConstant: -10000`, `springLength: 300`
- **Star topology:** `gravitationalConstant: -5000`, `centralGravity: 0.8`

### Node Styling

```javascript
{
  id: 1,
  label: "Name",
  color: "#667eea",           // Node color
  size: 25,                   // Node size
  shape: "box" | "dot" | "diamond",
  font: { size: 14, color: "#fff" },
  title: "Tooltip text"
}
```

### Edge Styling

```javascript
{
  from: 1,
  to: 2,
  label: "relationship",
  color: "#99ccff",           // Edge color
  width: 2,
  arrows: "to" | "from" | "both",
  smooth: { type: "continuous" },
  font: { size: 10 }
}
```

---

## Output Artifacts

### 1. Interactive Graph HTML
- File: `grafo_interactivo.html`
- Size: 15-30 KB
- Features:
  - Drag-and-drop nodes
  - Zoom/pan
  - Click for node details
  - Search/filter controls
  - Physics simulation

### 2. Analytics Report HTML
- File: `analytics.html`
- Size: 10-20 KB
- Features:
  - Bar charts (node/edge counts by type)
  - Doughnut charts (distribution)
  - Top-N tables
  - Network metrics (density, clustering coefficient)

### 3. Summary Markdown
- File: `reporte_grafo.md`
- Size: 5-15 KB
- Sections:
  - Metrics summary
  - Degree distribution
  - Findings and insights
  - Methodology notes

### 4. Raw Graph JSON
- File: `grafo.json`
- Size: 50-500 KB (depends on node/edge count)
- Usage: Feed to other visualization tools or APIs

---

## Advanced Features

### Subgraph Extraction

Filter by node type or edge type:

```javascript
function filterSubgraph(nodes, edges, nodeType) {
    const filtered_nodes = nodes.filter(n => n.tipo === nodeType);
    const node_ids = new Set(filtered_nodes.map(n => n.id));
    const filtered_edges = edges.filter(e => 
        node_ids.has(e.from) && node_ids.has(e.to)
    );
    return { filtered_nodes, filtered_edges };
}
```

### Community Detection

Identify clusters (requires library: `networkx` or `community.js`):

```python
import networkx as nx
from community import community_louvain

# Build graph
G = nx.Graph()
for edge in edges:
    G.add_edge(edge['from'], edge['to'])

# Detect communities
partition = community_louvain.best_partition(G)

# Assign colors by community
for node in nodes:
    community = partition.get(node['id'], 0)
    node['color'] = COLORS[community % len(COLORS)]
```

### Centrality Analysis

```python
import networkx as nx

G = nx.Graph()
for edge in edges:
    G.add_edge(edge['from'], edge['to'], weight=edge.get('peso', 1))

# Calculate centralities
degree_centrality = nx.degree_centrality(G)
betweenness = nx.betweenness_centrality(G, weight='weight')
closeness = nx.closeness_centrality(G, distance='weight')

# Rank nodes
top_nodes = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:10]
```

---

## Limitations & Workarounds

| Limitation | Impact | Workaround |
|-----------|--------|-----------|
| **>10,000 nodes** | Slow rendering, memory issues | Use node clustering or subgraph extraction |
| **Very dense graphs** | Edge clutter | Filter by edge weight threshold |
| **Huge labels** | Rendering artifacts | Truncate labels, use tooltips |
| **No 3D support** | Limited perspective | Use separate 3D library (Three.js) |
| **Static layout only** | Limited exploration | Add force-directed layout toggle |

---

## Best Practices

1. **Normalize node IDs:** Use integers or simple strings, not UUIDs
2. **Size by importance:** Use node size proportional to degree or centrality
3. **Color by type:** Assign consistent colors to node/edge types
4. **Label clarity:** Keep labels <30 chars, use abbreviations if needed
5. **Edge arrows:** Only use for directed graphs; remove for undirected
6. **Physics tuning:** Start with defaults, adjust if nodes bunch up or scatter
7. **Performance:** For >5,000 edges, pre-filter or cluster before rendering

---

## Troubleshooting

**Q: Graph doesn't appear**
A: Check browser console for errors. Verify JSON path and format. Ensure vis.js CDN is accessible.

**Q: Nodes all clustered in center**
A: Reduce `gravitationalConstant` (less negative), increase `springLength`

**Q: Edges overlapping nodes**
A: Enable edge smoothing: `smooth: { type: "continuous" }`

**Q: Search filter not working**
A: Ensure node `id` and `to`/`from` in edges use same data type (int vs string)

**Q: Performance issues with >5,000 nodes**
A: Disable physics simulation: `physics: { enabled: false }`

---

## Related Skills

- [`statistical-report`](../statistical-report/SKILL.md) — For tabular analytics
- [`graph-analysis`](../graph-analysis/SKILL.md) — For centrality/community detection
- [`create-table`](../create-table/SKILL.md) — For schema design before graph export

---

## Example Command

```bash
# Run the interactive graph report skill
datasyn graph-report \
  --nodes data/nodes.json \
  --edges data/edges.json \
  --output reports/ \
  --title "Contrataciones Públicas" \
  --physics-enabled \
  --layout force-directed
```

---

## Resources

- **vis.js documentation:** https://visjs.org/
- **React documentation:** https://react.dev/
- **Chart.js documentation:** https://www.chartjs.org/
- **NetworkX (Python graph library):** https://networkx.org/
- **Community detection:** https://python-louvain.readthedocs.io/

---

**Last updated:** 2026-06-05  
**Skill version:** 1.0  
**Status:** Production-ready
