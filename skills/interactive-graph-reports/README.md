# Interactive Graph Reports - Examples & Usage Guide

## Overview

This skill generates interactive, HTML-based graph visualizations from node/edge data. Output includes:
- **Interactive HTML report** (vis.js + React): Drag nodes, zoom, search, view details
- **Analytics HTML report** (Chart.js): Distribution charts and statistics
- **Graph JSON**: Structured data for other tools
- **Summary Markdown**: Key metrics and findings

---

## Quick Start (5 minutes)

### Example 1: Simple Network from DuckDB

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts/python").resolve()))

from helper_grafo_interactivo import (
    export_graph_data,
    generate_html_interactive,
    generate_analytics_html
)
import db

# Query data from DuckDB
con = db.connect()

organismos = con.execute("""
    SELECT organismo_id AS id, nombre AS label, 'organismo' AS tipo
    FROM silver.contrataciones_organismos
""").fetchall()

adjudicatarios = con.execute("""
    SELECT 100 + adjudicatario_id AS id, nombre AS label, 'adjudicatario' AS tipo
    FROM silver.contrataciones_adjudicatarios
""").fetchall()

edges = con.execute("""
    SELECT source_id AS 'from', target_id AS 'to', edge_type AS 'type'
    FROM silver.contrataciones_edges
""").fetchall()

con.close()

# Convert to dicts
nodes = [
    {'id': row[0], 'label': row[1], 'tipo': row[2]}
    for row in list(organismos) + list(adjudicatarios)
]

edges_list = [
    {'from': row[0], 'to': row[1], 'type': row[2]}
    for row in edges
]

# Export and generate reports
export_graph_data(nodes, edges_list, output_dir='reports/', filename='grafo.json')

generate_html_interactive(
    'reports/grafo.json',
    'reports/grafo_interactivo.html',
    title='Contrataciones Públicas'
)

generate_analytics_html(
    'reports/grafo.json',
    'reports/analisis.html',
    title='Análisis de Contrataciones'
)

print("✅ Reports generated:")
print("  - reports/grafo_interactivo.html (interactive)")
print("  - reports/analisis.html (analytics)")
print("  - reports/grafo.json (data)")
```

### Example 2: From Custom Data

```python
from helper_grafo_interactivo import export_graph_data, generate_html_interactive

# Your data
nodes = [
    {'id': 1, 'label': 'Company A', 'tipo': 'empresa'},
    {'id': 2, 'label': 'Company B', 'tipo': 'empresa'},
    {'id': 101, 'label': 'Person X', 'tipo': 'persona'},
]

edges = [
    {'from': 1, 'to': 2, 'type': 'PARTNER'},
    {'from': 1, 'to': 101, 'type': 'EMPLOYEE'},
]

# Generate
export_graph_data(nodes, edges, filename='mi_grafo.json')
generate_html_interactive('mi_grafo.json', title='Mi Red')

# Open
import webbrowser
webbrowser.open('mi_grafo_interactivo.html')
```

---

## Full Example: Contrataciones

### Step 1: Query & Export

```bash
# From the repo root:
uv run python << 'PYTHON'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts/python").resolve()))

from helper_grafo_interactivo import export_graph_data, generate_html_interactive, generate_analytics_html, get_top_nodes
import db

con = db.connect()

# Get all nodes
nodes_org = con.execute("SELECT organismo_id, nombre, tipo FROM silver.contrataciones_organismos").fetchall()
nodes_adj = con.execute("SELECT adjudicatario_id, nombre, tipo_persona FROM silver.contrataciones_adjudicatarios").fetchall()

nodes = [
    {'id': row[0], 'label': row[1], 'tipo': 'organismo'}
    for row in nodes_org
] + [
    {'id': 100 + row[0], 'label': row[1], 'tipo': 'adjudicatario', 'cuit': row[3]}
    for row in nodes_adj
]

# Get all edges
edges_raw = con.execute("SELECT source_id, target_id, edge_type, monto, boletin_fecha FROM silver.contrataciones_edges").fetchall()

edges = [
    {'from': row[0], 'to': row[1] if row[1] else None, 'type': row[2], 'peso': row[3], 'fecha': str(row[4])}
    for row in edges_raw if row[1] or row[2] == 'PUBLICA_AVISO'
]

con.close()

# Export & generate
export_graph_data(nodes, edges, filename='grafo_contrataciones.json')
generate_html_interactive('reports/grafo_contrataciones.json', 'reports/grafo_interactivo.html', 'Contrataciones')
generate_analytics_html('reports/grafo_contrataciones.json', 'reports/analytics.html', 'Análisis')

# Print top nodes
top = get_top_nodes(nodes, edges, top_n=5)
print("\n🏆 Top nodes by degree:")
for node_id, label, degree in top:
    print(f"  {label}: {degree} connections")
PYTHON
```

### Step 2: View Reports

```bash
# Interactive graph
open reports/grafo_interactivo.html

# Analytics
open reports/analytics.html

# Raw JSON
cat reports/grafo_contrataciones.json | jq '.estadisticas'
```

---

## Advanced Configuration

### Custom Node Colors

```python
colors = {
    'organismo': '#667eea',      # Blue
    'adjudicatario': '#764ba2',  # Purple
    'empresa': '#f093fb',         # Pink
    'default': '#cccccc'
}

generate_html_interactive(
    'grafo.json',
    node_colors=colors
)
```

### Disable Physics (Static Layout)

```python
generate_html_interactive(
    'grafo.json',
    physics_enabled=False  # Nodes won't move
)
```

### Custom Titles

```python
generate_html_interactive(
    'grafo.json',
    title='Red de Organismos y Contratistas',
    output_path='reports/custom_name.html'
)
```

---

## Data Format Reference

### Nodes JSON

```json
[
  {
    "id": 1,
    "label": "Node Name",
    "tipo": "category",
    "custom_field": "optional"
  }
]
```

**Required fields:**
- `id` (integer or string, unique)
- `label` (string, display name)
- `tipo` (string, for coloring and filtering)

**Optional fields:**
- Any custom field (CUIT, email, etc.)

### Edges JSON

```json
[
  {
    "from": 1,
    "to": 2,
    "type": "relationship_type",
    "peso": 50000,
    "fecha": "2026-06-01"
  }
]
```

**Required fields:**
- `from` (integer or string, node id)
- `to` (integer or string, node id)
- `type` (string, for labeling edges)

**Optional fields:**
- `peso` (number, for sizing edges)
- `fecha` (string, for filtering)

---

## Output Artifacts

### 1. Interactive HTML

**File:** `grafo_interactivo.html`  
**Size:** 15-30 KB  
**Features:**
- Drag nodes
- Zoom/pan with scroll
- Click to select node
- Search filter
- Fit to view button
- Real-time physics simulation

**Browser support:** Chrome, Firefox, Safari, Edge (modern versions)

### 2. Analytics HTML

**File:** `analytics.html`  
**Size:** 10-20 KB  
**Features:**
- Doughnut chart: node type distribution
- Bar chart: edge type distribution
- Responsive layout

### 3. Graph JSON

**File:** `grafo.json`  
**Size:** 50-500 KB  
**Schema:**
```json
{
  "nodes": [...],
  "edges": [...],
  "estadisticas": {
    "total_nodes": 56,
    "total_edges": 175,
    "node_types": {"organismo": 34, "adjudicatario": 22},
    "edge_types": {"PUBLICA_AVISO": 149, "ADJUDICA_A": 26},
    "avg_degree": 6.25
  }
}
```

---

## Troubleshooting

### Problem: Graph not rendering

**Cause:** JSON path incorrect or network CDN unavailable

**Solution:**
1. Check browser console (F12 → Console tab)
2. Verify JSON file exists and is valid: `jq '.' grafo.json`
3. Test CDN: try vis.js example page

### Problem: Nodes all clustered

**Cause:** Physics settings need tuning

**Solution:**
```python
# Edit generated HTML, change physics options:
physics: {
    barnesHut: {
        gravitationalConstant: -50000,  # More negative = more spread
        springLength: 250                # Longer edges
    }
}
```

### Problem: Too slow (>5,000 nodes)

**Cause:** Physics simulation too expensive

**Solution:**
```python
# Disable physics for static layout
generate_html_interactive('grafo.json', physics_enabled=False)

# Or filter subgraph before export
filtered_edges = [e for e in edges if e.get('peso', 0) > threshold]
```

### Problem: Edge labels not showing

**Cause:** Edges overlapping nodes

**Solution:** Edit HTML, add to edge config:
```javascript
smooth: { type: 'continuous' },
font: { size: 10 }
```

---

## Performance Tips

| Optimization | When to use | Impact |
|-------------|-----------|--------|
| **Disable physics** | Static layout OK | 10x faster rendering |
| **Filter edges** | Too many edges | 5x faster layout |
| **Node clustering** | >10K nodes | Manageable display |
| **Lazy loading** | Large JSON (>10MB) | Memory efficient |
| **Subgraph extraction** | Focus on subset | Cleaner visualization |

---

## Integration with Other Skills

### Use with `graph-analysis`

```bash
# 1. Generate interactive report (this skill)
uv run python generate_reports.py

# 2. Analyze graph structure (graph-analysis skill)
uv run python -m graph_analysis \
  --grafo reports/grafo.json \
  --metrics centrality,clustering,communities
```

### Use with `statistical-report`

```bash
# 1. Export node/edge statistics
uv run python -c "
  from helper_grafo_interactivo import export_graph_data, get_top_nodes
  ...
  top = get_top_nodes(nodes, edges, top_n=20)
  stats_df = pd.DataFrame(top, columns=['id', 'label', 'degree'])
  stats_df.to_csv('node_stats.csv')
"

# 2. Generate statistical report
datasyn statistical-report \
  --input node_stats.csv \
  --output reports/stats.html
```

---

## FAQ

**Q: Can I include edge weights in visualization?**  
A: Yes, use `peso` field in edges to control edge width:
```javascript
width: Math.log(edge.peso + 1) * 2
```

**Q: How do I add node images/avatars?**  
A: Edit HTML, replace node rendering with images via `image` property in vis.js

**Q: Can I export graph to other formats (GraphML, GexF)?**  
A: Not built-in, but `networkx` can convert:
```python
import networkx as nx
G = nx.Graph()
# ... build graph
nx.write_graphml(G, 'grafo.graphml')
```

**Q: How do I detect communities/clusters?**  
A: Use `graph-analysis` skill or `python-louvain` library

**Q: Can multiple reports share same JSON?**  
A: Yes! Generate once, create multiple HTML reports with different colors/titles

---

## Related Resources

- [vis.js Documentation](https://visjs.org/)
- [React 18 Docs](https://react.dev/)
- [Chart.js Guide](https://www.chartjs.org/docs/latest/)
- [NetworkX (Python)](https://networkx.org/)
- [D3.js (Alternative visualization)](https://d3js.org/)

---

**Last updated:** 2026-06-05  
**Skill version:** 1.0  
**Helper script:** `helper_grafo_interactivo.py`
