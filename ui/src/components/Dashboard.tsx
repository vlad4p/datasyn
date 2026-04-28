import { useCallback, useEffect, useMemo, useState } from "react";
import type { BrainHealth, SkillInventoryItem, ToolInventoryItem } from "../api";
import { getHealth, getToolsInventory } from "../api";

import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type Props = { className?: string; locale: UiLocale };
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
  scrapper_list_sources: "List supported public data sources.",
  scrapper_indec_mercado_laboral_list: "Probe INDEC EPH files by period (no download).",
  scrapper_indec_mercado_laboral_download: "Download and unzip INDEC EPH data into /data-local.",
  dagster_list_projects: "List scaffolded Dagster projects.",
  dagster_create_project: "Create a Dagster project scaffold.",
  dagster_add_asset: "Add an asset module to a Dagster project.",
  dagster_add_job: "Add a Dagster job to a project.",
  dagster_add_schedule: "Add a Dagster schedule to a project.",
  dagster_add_sensor: "Add a Dagster sensor to a project.",
  dagster_build_image: "Build Docker image for Dagster user code.",
  dagster_deploy: "Build/deploy project container on Docker network.",
  dagster_compose_force_recreate: "Force recreate target compose services.",
  dagster_stop: "Stop project container.",
  dagster_remove: "Remove project container/image.",
  dagster_logs: "Read project container logs.",
  dagster_status: "Show project container status.",
  dagster_daemon_info: "Inspect host Docker daemon availability.",
  dagster_catalog_get_schema: "Read metadata catalog schema (PostgreSQL).",
  dagster_catalog_execute_query: "Run one guarded SQL query on metadata catalog.",
  write_todos: "Persist task checklist state for multi-step turns.",
  ls: "List files/directories in the project virtual FS.",
  read_file: "Read file contents from project virtual FS.",
  write_file: "Create/overwrite files in project virtual FS.",
  edit_file: "Apply targeted edits to files in project virtual FS.",
  glob: "Find files by pattern in project virtual FS.",
  grep: "Search text pattern in project files.",
  task: "Launch subagent for delegated work.",
};

const TOOL_EXAMPLES: Record<string, string> = {
  duckdb_get_schema: "Use when starting a task: inspect available tables before querying.",
  duckdb_execute_query: "Example: run an aggregate query (COUNT/GROUP BY) instead of SELECT *.",
  duckdb_list_data_mount: "Example: list /data-local/indec recursively before ingest.",
  scrapper_indec_mercado_laboral_list: "Example: check if 2025 Q3 source files exist before download.",
  scrapper_indec_mercado_laboral_download: "Example: download and unzip EPH files, then ingest into DuckDB.",
  dagster_catalog_execute_query: "Example: upsert dataset_entity metadata with ON CONFLICT.",
  dagster_catalog_get_schema: "Example: inspect public catalog tables before writing SQL.",
  write_todos: "Use for multi-step work tracking during long implementations.",
  read_file: "Use to inspect AGENTS.md or SKILL.md before acting.",
  write_file: "Use to create reports or generated artifacts under reports/.",
  edit_file: "Use for targeted code edits preserving surrounding context.",
  glob: "Use to locate files by pattern (e.g., **/*.tsx).",
  grep: "Use to find exact symbols/strings in the repo.",
  task: "Use when delegating broad exploration to a subagent.",
};

function inferToolMeta(name: string): ToolMeta {
  const n = name.trim();
  if (BUILTIN_HELPERS.includes(n)) {
    return {
      name: n,
      category: "helper",
      mcpServer: "deepagents",
      title: n,
      description: TOOL_DESCRIPTIONS[n] ?? "Built-in helper tool.",
      example: TOOL_EXAMPLES[n] ?? "Built-in helper for filesystem and orchestration.",
    };
  }
  const server = n.includes("_") ? n.split("_", 1)[0] : "unknown";
  return {
    name: n,
    category: "mcp",
    mcpServer: server,
    title: n,
    description: TOOL_DESCRIPTIONS[n] ?? "MCP tool available at runtime.",
    example: TOOL_EXAMPLES[n] ?? "Use when this capability is required in a task flow.",
  };
}

export function Dashboard({ className, locale }: Props) {
  const d = uiStrings(locale).dashboard;
  const [health, setHealth] = useState<string>("—");
  const [healthError, setHealthError] = useState<string | null>(null);
  const [, setHealthPayload] = useState<BrainHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const [inventoryTools, setInventoryTools] = useState<ToolInventoryItem[]>([]);
  const [inventorySkills, setInventorySkills] = useState<SkillInventoryItem[]>([]);
  const [inventoryError, setInventoryError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setHealthError(null);
    setInventoryError(null);

    try {
      const h = await getHealth();
      setHealthPayload(h);
      setHealth(h.status);
    } catch (e) {
      setHealthPayload(null);
      setHealth("error");
      setHealthError(String(e));
    }
    try {
      const inv = await getToolsInventory();
      setInventoryTools(inv.tools ?? []);
      setInventorySkills(inv.skills ?? []);
      if (inv.mcp_error) {
        setInventoryError(inv.mcp_error);
      }
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
      if (t.source === "helper") {
        return inferToolMeta(t.name);
      }
      return {
        ...inferToolMeta(t.name),
        category: "mcp" as const,
        mcpServer: t.server || inferToolMeta(t.name).mcpServer,
      };
    });
    const skillRows: ToolMeta[] = inventorySkills.map((s) => ({
      name: s.name,
      category: "skill",
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
    const categoryOrder: Record<ToolMeta["category"], number> = {
      mcp: 0,
      skill: 1,
      helper: 2, // Deep Agents helpers at the bottom
    };
    return Array.from(map.values()).sort((a, b) => {
      const diff = categoryOrder[a.category] - categoryOrder[b.category];
      if (diff !== 0) return diff;
      return a.name.localeCompare(b.name);
    });
  }, [d.skillBlurb, d.skillExample, inventorySkills, inventoryTools]);
  const selectedMeta = useMemo(
    () => toolRows.find((t) => t.name === selectedTool) ?? toolRows[0] ?? null,
    [toolRows, selectedTool],
  );

  useEffect(() => {
    if (!selectedTool && toolRows.length > 0) {
      setSelectedTool(toolRows[0].name);
    }
  }, [selectedTool, toolRows]);

  return (
    <aside className={`dashboard ${className ?? ""}`}>
      <div className="dashboard-header">
        <h2>{d.title}</h2>
        <button type="button" className="btn ghost" onClick={() => void refresh()} disabled={loading}>
          {d.refresh}
        </button>
      </div>

      <section className="dash-card">
        <h3>{d.toolsInModel}</h3>
        <dl className="dash-dl">
          <dt>{d.status}</dt>
          <dd>
            <span className={`pill ${health === "ok" ? "ok" : "bad"}`}>{loading ? "…" : health}</span>
          </dd>
        </dl>
        {healthError && (
          <p className="error small dash-detail">
            {healthError}
          </p>
        )}
        <p className="small muted mt">
          {d.toolsBlurb}
        </p>
        {inventoryError && <p className="error small dash-detail">{inventoryError}</p>}
        <p className="tiny muted mt">
          {d.tableHint(toolRows.length)}
        </p>
        <div className="dash-table-wrap compact scroll-10">
          <table className="dash-table compact">
            <thead>
              <tr>
                <th>{d.colTool}</th>
                <th>{d.colType}</th>
                <th>{d.colMcp}</th>
              </tr>
            </thead>
            <tbody>
              {toolRows.map((tool) => (
                <tr
                  key={tool.name}
                  className={selectedMeta?.name === tool.name ? "selected" : ""}
                  onClick={() => setSelectedTool(tool.name)}
                >
                  <td className="mono">{tool.name}</td>
                  <td>{tool.category}</td>
                  <td>{tool.mcpServer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selectedMeta && (
          <article className="tool-card unified">
            <header className="tool-card-header">
              <h4 className="mono">{selectedMeta.title}</h4>
              <span className={`pill cat-${selectedMeta.category}`}>{selectedMeta.category}</span>
            </header>
            <p className="small">{selectedMeta.description}</p>
            <dl className="dash-dl tool-card-info">
              <dt>{d.name}</dt>
              <dd className="mono">{selectedMeta.name}</dd>
              <dt>{d.type}</dt>
              <dd>{selectedMeta.category}</dd>
              <dt>{d.mcpServer}</dt>
              <dd>{selectedMeta.mcpServer}</dd>
              {selectedMeta.sourcePath && (
                <>
                  <dt>{d.path}</dt>
                  <dd className="mono">{selectedMeta.sourcePath}</dd>
                </>
              )}
            </dl>
            <div className="tool-card-section">
              <h5>{d.exampleUsage}</h5>
              <p className="small muted">{selectedMeta.example}</p>
            </div>
          </article>
        )}
      </section>
    </aside>
  );
}
