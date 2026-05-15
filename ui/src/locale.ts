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
  /** Workspace tab: primary assistant view */
  navChat: string;
  /** Reset conversation and stored history */
  newChat: string;
  /** `aria-label` for Chat / Dashboard tab bar */
  workspaceNavAria: string;
  chatEmpty: string;
  placeholder: string;
  send: string;
  loading: string;
  chatAria: string;
  /** Section label for streamed subagent (task) output */
  subagentLabel: string;
  /** Small header above live graph/tool status while streaming */
  streamThinkingTitle: string;
  /** Quick prompts when locale matches */
  suggestions: string[];
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
  tagline: "Warehouse agent · health",
  navChat: "Chat",
  newChat: "New chat",
  workspaceNavAria: "Main workspace",
  chatEmpty: `Ask anything. Replies can include **Markdown tables**, **Mermaid** diagrams (fenced \`mermaid\`), **Vega-Lite** charts (fenced \`vega-lite\` JSON), **Plotly** interactive charts (fenced \`plotly\` JSON with \`data\` array), and images (\`https://\`, \`data:image/…\`, or files under \`/project/reports/…\` served by the API).`,
  placeholder: "Message…",
  send: "Send",
  loading: "Loading",
  chatAria: "Agent chat",
  subagentLabel: "Specialist",
  streamThinkingTitle: "Thinking",
  suggestions: [
    "List all files under /data-local (including subfolders) using duckdb tools.",
    "What models does the brain use? Summarize litellm_base and CHAT_MODEL from your tools.",
    "Run SELECT * FROM example_sales LIMIT 10 and format results as a markdown table.",
    "Reply with a Mermaid flowchart in a fenced mermaid code block (ingest → warehouse → report).",
  ],
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
  tagline: "Agente de almacén · estado",
  navChat: "Chat",
  newChat: "Nuevo chat",
  workspaceNavAria: "Área principal",
  chatEmpty: `Pregunta lo que quieras. Las respuestas pueden incluir **tablas Markdown**, diagramas **Mermaid** (bloque \`mermaid\`), gráficos **Vega-Lite** (JSON en bloque \`vega-lite\`), gráficos interactivos **Plotly** (JSON en bloque \`plotly\` con arreglo \`data\`) e imágenes (\`https://\`, \`data:image/…\` o archivos bajo \`/project/reports/…\` servidos por la API).`,
  placeholder: "Mensaje…",
  send: "Enviar",
  loading: "Cargando",
  chatAria: "Chat con el agente",
  subagentLabel: "Especialista",
  streamThinkingTitle: "Pensando",
  suggestions: [
    "Lista todos los archivos bajo /data-local (incl. subcarpetas) con las herramientas duckdb.",
    "¿Qué modelos usa el brain? Resume litellm_base y CHAT_MODEL a partir de tus herramientas.",
    "Ejecuta SELECT * FROM example_sales LIMIT 10 y formatea el resultado como tabla Markdown.",
    "Responde con un diagrama Mermaid en un bloque de código mermaid (ingest → almacén → reporte).",
  ],
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
