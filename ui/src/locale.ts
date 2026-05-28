/** UI + API locale: matches `POST /agent/chat` body `locale`. */
export type UiLocale = "en" | "es";

const STORAGE_KEY = "datacyber-ui-locale";

export function readStoredLocale(): UiLocale {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "es" || v === "en") return v;
  } catch {
    /* ignore */
  }
  return "en";
}

export function persistLocale(locale: UiLocale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    /* ignore */
  }
}

type Strings = {
  tagline: string;
  navAgent: string;
  navDatasets: string;
  navAnalyses: string;
  /** @deprecated use navAgent */
  navChat: string;
  newChat: string;
  workspaceNavAria: string;
  agentTitle: string;
  agentOnline: string;
  agentOffline: string;
  agentPlaceholder: string;
  exportAnalysis: string;
  exporting: string;
  exportSuccess: string;
  exportFailed: string;
  chatEmpty: string;
  placeholder: string;
  send: string;
  loading: string;
  chatAria: string;
  subagentLabel: string;
  streamThinkingTitle: string;
  modelSwitch: {
    switchTitle: string;
    searchPlaceholder: string;
    freeOnly: string;
    freeBadge: string;
    currentBadge: string;
    loading: string;
    empty: string;
    loadFailed: string;
  };
  suggestions: string[];
  catalog: {
    title: string;
    hint: string;
    refresh: string;
    loading: string;
    empty: string;
    searchPlaceholder: string;
    filterLabel: string;
    filterAll: string;
    filterBronze: string;
    filterSilver: string;
    filterGold: string;
    noDescription: string;
    columns: string;
    catalogUnavailable: string;
    catalogOk: string;
    dagsterUnavailable: string;
    dagsterOk: string;
    filterDuckdbTable: string;
    filterDuckdbAll: string;
    dagsterAsset: string;
    lineageTitle: string;
    lineageUpstream: string;
    lineageDownstream: string;
    lineageEmpty: string;
    detailTitle: string;
    close: string;
    analyzeInAgent: string;
    dagsterJob: string;
    dagsterMetadata: string;
    dagsterLatestMaterialization: string;
    dagsterTableFqn: string;
    dagsterOwners: string;
    dagsterComputeKind: string;
    columnsCatalog: string;
    columnsWarehouse: string;
    systemTools: string;
  };
  analyses: {
    title: string;
    hint: string;
    loading: string;
    empty: string;
    back: string;
    messageCount: (n: number) => string;
  };
  dashboard: {
    title: string;
    refresh: string;
    mcpSectionTitle: string;
    mcpSectionBlurb: string;
    pickServer: string;
    toolCount: (n: number) => string;
    helpersGroup: string;
    skillsGroup: string;
    status: string;
    toolsBlurb: string;
    tableHint: (n: number) => string;
    colTool: string;
    colType: string;
    colMcp: string;
    name: string;
    type: string;
    mcpServer: string;
    path: string;
    exampleUsage: string;
    skillBlurb: string;
    skillExample: string;
    warehouseTitle: string;
    warehouseHint: string;
    layerBronze: string;
    layerSilver: string;
    layerGold: string;
    layerOther: string;
    emptyLayer: string;
  };
};

const EN: Strings = {
  tagline: "Warehouse agent · datasets · analyses",
  navAgent: "Agent",
  navDatasets: "Datasets",
  navAnalyses: "Analyses",
  navChat: "Agent",
  newChat: "New chat",
  workspaceNavAria: "Main workspace",
  agentTitle: "Warehouse agent",
  agentOnline: "Online",
  agentOffline: "Offline",
  agentPlaceholder: "Ask the warehouse agent…",
  exportAnalysis: "Export analysis",
  exporting: "Exporting…",
  exportSuccess: "Analysis exported.",
  exportFailed: "Export failed",
  chatEmpty: `Ask anything. Replies can include **Markdown tables**, **Mermaid** diagrams (fenced \`mermaid\`), **Vega-Lite** charts (fenced \`vega-lite\` JSON), **Plotly** interactive charts (fenced \`plotly\` JSON with \`data\` array), and images (\`https://\`, \`data:image/…\`, or files under \`/project/reports/…\` served by the API).`,
  placeholder: "Message…",
  send: "Send",
  loading: "Loading",
  chatAria: "Agent chat",
  subagentLabel: "Specialist",
  streamThinkingTitle: "Thinking",
  modelSwitch: {
    switchTitle: "Switch model",
    searchPlaceholder: "Search models…",
    freeOnly: "Free only",
    freeBadge: "Free",
    currentBadge: "Active",
    loading: "Loading models…",
    empty: "No models match.",
    loadFailed: "Could not load models from OpenRouter.",
  },
  suggestions: [
    "List all files under /data-local (including subfolders) using duckdb tools.",
    "What models does the brain use? Summarize litellm_base and CHAT_MODEL from your tools.",
    "Run SELECT * FROM example_sales LIMIT 10 and format results as a markdown table.",
    "Reply with a Mermaid flowchart in a fenced mermaid code block (ingest → warehouse → report).",
  ],
  catalog: {
    title: "Dataset catalog",
    hint: "DuckDB tables merged with the Dagster GraphQL catalog (assets, jobs, lineage).",
    refresh: "Refresh",
    loading: "Loading…",
    empty: "No datasets match your filters.",
    searchPlaceholder: "Search name, FQN, tags…",
    filterLabel: "Medallion layer",
    filterAll: "All",
    filterBronze: "Bronze",
    filterSilver: "Silver",
    filterGold: "Gold",
    noDescription: "No catalog description",
    columns: "Columns",
    catalogUnavailable: "Postgres catalog MCP not configured.",
    catalogOk: "Postgres catalog metadata merged.",
    dagsterUnavailable: "Dagster unreachable — set DAGSTER_URL in .env (host:port only, e.g. http://10.0.0.1:3001).",
    dagsterOk: "Dagster asset catalog loaded via GraphQL.",
    filterDuckdbTable: "DuckDB table",
    filterDuckdbAll: "All warehouse tables",
    dagsterAsset: "Dagster asset",
    lineageTitle: "Lineage",
    lineageUpstream: "Upstream (dependencies)",
    lineageDownstream: "Downstream (dependents)",
    lineageEmpty: "No lineage edges in Dagster for this asset.",
    detailTitle: "Dataset detail",
    close: "Close",
    analyzeInAgent: "Analyze in Agent",
    dagsterJob: "Dagster job",
    dagsterMetadata: "Asset metadata (latest materialization)",
    dagsterLatestMaterialization: "Latest materialization",
    dagsterTableFqn: "Warehouse table",
    dagsterOwners: "Owners",
    dagsterComputeKind: "Compute kind",
    columnsCatalog: "Catalog columns",
    columnsWarehouse: "Warehouse columns",
    systemTools: "System & tools",
  },
  analyses: {
    title: "Last analyses",
    hint: "Exported report-style summaries from agent conversations.",
    loading: "Loading…",
    empty: "No exported analyses yet. Use Export analysis in the Agent tab.",
    back: "Back to list",
    messageCount: (n) => `${n} message${n === 1 ? "" : "s"}`,
  },
  dashboard: {
    title: "Dashboard",
    refresh: "Refresh",
    mcpSectionTitle: "MCP available",
    mcpSectionBlurb: "Pick an MCP server to see its tools. Helpers and project skills are separate groups.",
    pickServer: "Server",
    toolCount: (n) => `${n} tool${n === 1 ? "" : "s"}`,
    helpersGroup: "Helpers",
    skillsGroup: "Skills",
    status: "Status",
    toolsBlurb: "All tools available now: MCP tools + built-in helpers + discovered skills.",
    tableHint: (n) => `${n} total · scroll the table to see all`,
    colTool: "Tool",
    colType: "Type",
    colMcp: "MCP",
    name: "Name",
    type: "Type",
    mcpServer: "MCP server",
    path: "Path",
    exampleUsage: "Example usage",
    skillBlurb: "Skill available to the model (auto-discovered from /skills).",
    skillExample: "Use when a request matches this workflow/domain.",
    warehouseTitle: "Warehouse tables",
    warehouseHint: "Live objects from DuckDB (schemas bronze · silver · gold).",
    layerBronze: "Bronze",
    layerSilver: "Silver",
    layerGold: "Gold",
    layerOther: "Other schemas",
    emptyLayer: "No tables",
  },
};

const ES: Strings = {
  tagline: "Agente · datasets · análisis",
  navAgent: "Agente",
  navDatasets: "Datasets",
  navAnalyses: "Análisis",
  navChat: "Agente",
  newChat: "Nuevo chat",
  workspaceNavAria: "Área principal",
  agentTitle: "Agente de almacén",
  agentOnline: "En línea",
  agentOffline: "Sin conexión",
  agentPlaceholder: "Pregunta al agente de almacén…",
  exportAnalysis: "Exportar análisis",
  exporting: "Exportando…",
  exportSuccess: "Análisis exportado.",
  exportFailed: "Error al exportar",
  chatEmpty: `Pregunta lo que quieras. Las respuestas pueden incluir **tablas Markdown**, diagramas **Mermaid** (bloque \`mermaid\`), gráficos **Vega-Lite** (JSON en bloque \`vega-lite\`), gráficos interactivos **Plotly** (JSON en bloque \`plotly\` con arreglo \`data\`) e imágenes (\`https://\`, \`data:image/…\` o archivos bajo \`/project/reports/…\` servidos por la API).`,
  placeholder: "Mensaje…",
  send: "Enviar",
  loading: "Cargando",
  chatAria: "Chat con el agente",
  subagentLabel: "Especialista",
  streamThinkingTitle: "Pensando",
  modelSwitch: {
    switchTitle: "Cambiar modelo",
    searchPlaceholder: "Buscar modelos…",
    freeOnly: "Solo gratis",
    freeBadge: "Gratis",
    currentBadge: "Activo",
    loading: "Cargando modelos…",
    empty: "Ningún modelo coincide.",
    loadFailed: "No se pudieron cargar modelos desde OpenRouter.",
  },
  suggestions: [
    "Lista todos los archivos bajo /data-local (incl. subcarpetas) con las herramientas duckdb.",
    "¿Qué modelos usa el brain? Resume litellm_base y CHAT_MODEL a partir de tus herramientas.",
    "Ejecuta SELECT * FROM example_sales LIMIT 10 y formatea el resultado como tabla Markdown.",
    "Responde con un diagrama Mermaid en un bloque de código mermaid (ingest → almacén → reporte).",
  ],
  catalog: {
    title: "Catálogo de datasets",
    hint: "Tablas DuckDB fusionadas con el catálogo Dagster GraphQL (assets, jobs, lineage).",
    refresh: "Actualizar",
    loading: "Cargando…",
    empty: "Ningún dataset coincide con los filtros.",
    searchPlaceholder: "Buscar nombre, FQN, tags…",
    filterLabel: "Capa medallion",
    filterAll: "Todos",
    filterBronze: "Bronze",
    filterSilver: "Silver",
    filterGold: "Gold",
    noDescription: "Sin descripción en catálogo",
    columns: "Columnas",
    catalogUnavailable: "Catálogo Postgres MCP no configurado.",
    catalogOk: "Metadatos del catálogo Postgres fusionados.",
    dagsterUnavailable: "Dagster no disponible — configurá DAGSTER_URL en .env (solo host:puerto, ej. http://10.0.0.1:3001).",
    dagsterOk: "Catálogo de assets Dagster cargado vía GraphQL.",
    filterDuckdbTable: "Tabla DuckDB",
    filterDuckdbAll: "Todas las tablas",
    dagsterAsset: "Asset Dagster",
    lineageTitle: "Linaje",
    lineageUpstream: "Upstream (dependencias)",
    lineageDownstream: "Downstream (dependientes)",
    lineageEmpty: "Sin aristas de linaje en Dagster para este asset.",
    detailTitle: "Detalle del dataset",
    close: "Cerrar",
    analyzeInAgent: "Analizar en Agente",
    dagsterJob: "Job Dagster",
    dagsterMetadata: "Metadatos del asset (última materialización)",
    dagsterLatestMaterialization: "Última materialización",
    dagsterTableFqn: "Tabla en almacén",
    dagsterOwners: "Owners",
    dagsterComputeKind: "Compute kind",
    columnsCatalog: "Columnas (catálogo)",
    columnsWarehouse: "Columnas (almacén)",
    systemTools: "Sistema y herramientas",
  },
  analyses: {
    title: "Últimos análisis",
    hint: "Resúmenes exportados en estilo informe desde conversaciones con el agente.",
    loading: "Cargando…",
    empty: "Aún no hay análisis exportados. Usa Exportar análisis en la pestaña Agente.",
    back: "Volver al listado",
    messageCount: (n) => (n === 1 ? "1 mensaje" : `${n} mensajes`),
  },
  dashboard: {
    title: "Panel",
    refresh: "Actualizar",
    mcpSectionTitle: "MCP disponibles",
    mcpSectionBlurb: "Elige un servidor MCP para ver sus herramientas. Helpers y skills del proyecto van aparte.",
    pickServer: "Servidor",
    toolCount: (n) => (n === 1 ? "1 herramienta" : `${n} herramientas`),
    helpersGroup: "Helpers",
    skillsGroup: "Skills",
    status: "Estado",
    toolsBlurb: "Todas las herramientas: MCP + helpers internos + skills descubiertas.",
    tableHint: (n) => `${n} en total · desplázate en la tabla para ver todas`,
    colTool: "Herramienta",
    colType: "Tipo",
    colMcp: "MCP",
    name: "Nombre",
    type: "Tipo",
    mcpServer: "Servidor MCP",
    path: "Ruta",
    exampleUsage: "Ejemplo de uso",
    skillBlurb: "Skill disponible para el modelo (auto-descubierta bajo /skills).",
    skillExample: "Úsala cuando el pedido encaje con este flujo o dominio.",
    warehouseTitle: "Tablas del almacén",
    warehouseHint: "Objetos en DuckDB por capa (bronze · silver · gold).",
    layerBronze: "Bronze",
    layerSilver: "Silver",
    layerGold: "Gold",
    layerOther: "Otros esquemas",
    emptyLayer: "Sin tablas",
  },
};

export function uiStrings(locale: UiLocale): Strings {
  return locale === "es" ? ES : EN;
}
