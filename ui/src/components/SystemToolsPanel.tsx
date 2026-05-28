import { useCallback, useEffect, useMemo, useState } from "react";
import type { SkillInventoryItem, ToolInventoryItem } from "../api";
import { getHealth, getToolsInventory } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type ToolMeta = {
  name: string;
  category: "mcp" | "helper" | "skill";
  mcpServer: string;
  title: string;
  description: string;
  sourcePath?: string;
  example: string;
};

const BUILTIN_HELPERS = [
  "write_todos",
  "ls",
  "read_file",
  "write_file",
  "edit_file",
  "glob",
  "grep",
  "task",
];

const TOOL_DESCRIPTIONS: Record<string, string> = {
  duckdb_get_schema: "List schemas/tables/views available in DuckDB.",
  duckdb_execute_query: "Run one DuckDB SQL statement (SELECT/DDL/DML).",
  duckdb_list_data_mount: "List files and directories under /data-local.",
  dagster_catalog_get_schema: "Read metadata catalog schema (PostgreSQL).",
  dagster_catalog_execute_query: "Run one guarded SQL query on metadata catalog.",
};

const TOOL_EXAMPLES: Record<string, string> = {
  duckdb_execute_query: "Example: run an aggregate query (COUNT/GROUP BY).",
  dagster_catalog_execute_query: "Example: search dataset_entity via FTS.",
};

function inferToolMeta(name: string, locale: UiLocale): ToolMeta {
  const d = uiStrings(locale).dashboard;
  const n = name.trim();
  if (BUILTIN_HELPERS.includes(n)) {
    return {
      name: n,
      category: "helper",
      mcpServer: "deepagents",
      title: n,
      description: TOOL_DESCRIPTIONS[n] ?? "Built-in helper tool.",
      example: TOOL_EXAMPLES[n] ?? "Built-in helper.",
    };
  }
  const server = n.includes("_") ? n.split("_", 1)[0] : "unknown";
  return {
    name: n,
    category: "mcp",
    mcpServer: server,
    title: n,
    description: TOOL_DESCRIPTIONS[n] ?? "MCP tool available at runtime.",
    example: TOOL_EXAMPLES[n] ?? d.skillExample,
  };
}

type Props = { locale: UiLocale };

export function SystemToolsPanel({ locale }: Props) {
  const d = uiStrings(locale).dashboard;
  const [health, setHealth] = useState("—");
  const [inventoryTools, setInventoryTools] = useState<ToolInventoryItem[]>([]);
  const [inventorySkills, setInventorySkills] = useState<SkillInventoryItem[]>([]);
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [selectedServer, setSelectedServer] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setInventoryError(null);
    try {
      const h = await getHealth();
      setHealth(h.status);
    } catch {
      setHealth("error");
    }
    try {
      const inv = await getToolsInventory();
      setInventoryTools(inv.tools ?? []);
      setInventorySkills(inv.skills ?? []);
      if (inv.mcp_error) setInventoryError(inv.mcp_error);
    } catch (e) {
      setInventoryTools([]);
      setInventorySkills([]);
      setInventoryError(String(e));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toolRows = useMemo(() => {
    const fromInventory = inventoryTools.map((t) => {
      const base = inferToolMeta(t.name, locale);
      if (t.source === "mcp") {
        return { ...base, mcpServer: t.server || base.mcpServer };
      }
      return base;
    });
    const skillRows: ToolMeta[] = inventorySkills.map((s) => ({
      name: s.name,
      category: "skill" as const,
      mcpServer: "skills",
      title: s.name,
      description: d.skillBlurb,
      sourcePath: s.path,
      example: d.skillExample,
    }));
    const map = new Map<string, ToolMeta>();
    for (const row of [...fromInventory, ...skillRows]) {
      if (!map.has(row.name)) map.set(row.name, row);
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [d.skillBlurb, d.skillExample, inventorySkills, inventoryTools, locale]);

  const serverGroups = useMemo(() => {
    const mcp = new Set<string>();
    for (const t of inventoryTools) {
      if (t.source === "mcp") {
        mcp.add((t.server || "").trim() || inferToolMeta(t.name, locale).mcpServer);
      }
    }
    const priority = ["duckdb", "storage", "dagster"];
    const ordered = priority.filter((x) => mcp.has(x));
    const rest = [...mcp].filter((x) => !priority.includes(x)).sort();
    const out = [...ordered, ...rest];
    if (inventoryTools.some((t) => t.source === "helper")) out.push("__helpers__");
    if (inventorySkills.length > 0) out.push("__skills__");
    return out;
  }, [inventorySkills, inventoryTools, locale]);

  const toolsForServer = useMemo(() => {
    if (!selectedServer) return [];
    if (selectedServer === "__helpers__") return toolRows.filter((t) => t.category === "helper");
    if (selectedServer === "__skills__") return toolRows.filter((t) => t.category === "skill");
    return toolRows.filter((t) => t.category === "mcp" && t.mcpServer === selectedServer);
  }, [toolRows, selectedServer]);

  useEffect(() => {
    if (serverGroups.length === 0) {
      setSelectedServer(null);
      return;
    }
    setSelectedServer((prev) => (prev && serverGroups.includes(prev) ? prev : serverGroups[0]!));
  }, [serverGroups]);

  const chipLabel = (key: string) => {
    if (key === "__helpers__") return d.helpersGroup;
    if (key === "__skills__") return d.skillsGroup;
    const pretty: Record<string, string> = { duckdb: "DuckDB", storage: "Storage", dagster: "Dagster" };
    return pretty[key] ?? key;
  };

  return (
    <div className="system-tools-body">
      <dl className="dash-dl compact-status">
        <dt>{d.status}</dt>
        <dd>
          <span className={`pill ${health === "ok" ? "ok" : "bad"}`}>{loading ? "…" : health}</span>
        </dd>
      </dl>
      {inventoryError && <p className="error small">{inventoryError}</p>}
      <p className="small muted">{d.mcpSectionBlurb}</p>
      <button type="button" className="btn ghost" onClick={() => void refresh()} disabled={loading}>
        {d.refresh}
      </button>
      <div className="mcp-pick-row" style={{ marginTop: "0.75rem" }}>
        <div className="mcp-server-chips" role="tablist">
          {serverGroups.map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={selectedServer === key}
              className={`mcp-server-chip ${selectedServer === key ? "selected" : ""}`}
              onClick={() => setSelectedServer(key)}
            >
              {chipLabel(key)}
            </button>
          ))}
        </div>
      </div>
      <div className="mcp-tool-cards-grid" style={{ marginTop: "0.75rem" }}>
        {toolsForServer.map((tool) => (
          <article key={tool.name} className="mcp-tool-card">
            <header className="mcp-tool-card-head">
              <span className="mono mcp-tool-name">{tool.name}</span>
              <span className={`pill sm cat-${tool.category}`}>{tool.category}</span>
            </header>
            <p className="mcp-tool-desc">{tool.description}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
