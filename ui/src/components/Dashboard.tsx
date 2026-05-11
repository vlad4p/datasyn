import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  BrainHealth,
  SkillInventoryItem,
  ToolInventoryItem,
  WarehouseTablesResponse,
} from "../api";
import { getHealth, getToolsInventory, getWarehouseTables } from "../api";

import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type Props = { className?: string; locale: UiLocale; id?: string };
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
  storage_list_buckets: "List MinIO/S3 buckets on the configured endpoint.",
  storage_list_objects: "List object keys in a bucket (optional prefix).",
  storage_get_object_text: "Read a text object from a bucket (size-capped).",
  storage_put_object_text: "Write text content to an object key.",
  storage_delete_object: "Delete an object from a bucket.",
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
  storage_list_objects: "Example: list keys under indec/mercado_laboral in the data-local bucket.",
  storage_get_object_text: "Example: read a small metadata or CSV object from MinIO as text.",
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

const EMPTY_WAREHOUSE: WarehouseTablesResponse = {
  status: "ok",
  layers: { bronze: [], silver: [], gold: [] },
  other: [],
};

export function Dashboard({ className, locale, id }: Props) {
  const d = uiStrings(locale).dashboard;
  const [health, setHealth] = useState<string>("—");
  const [healthError, setHealthError] = useState<string | null>(null);
  const [, setHealthPayload] = useState<BrainHealth | null>(null);
  const [loading, setLoading] = useState(true);
  /** Selected MCP server key, or ``__helpers__`` / ``__skills__`` for non-MCP groups. */
  const [selectedServer, setSelectedServer] = useState<string | null>(null);
  const [inventoryTools, setInventoryTools] = useState<ToolInventoryItem[]>([]);
  const [inventorySkills, setInventorySkills] = useState<SkillInventoryItem[]>([]);
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [warehouse, setWarehouse] = useState<WarehouseTablesResponse>(EMPTY_WAREHOUSE);

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
    try {
      const w = await getWarehouseTables();
      setWarehouse(w);
    } catch (e) {
      setWarehouse({
        ...EMPTY_WAREHOUSE,
        status: "error",
        error: String(e),
      });
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
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [d.skillBlurb, d.skillExample, inventorySkills, inventoryTools]);

  const serverGroups = useMemo(() => {
    const mcp = new Set<string>();
    for (const t of inventoryTools) {
      if (t.source === "mcp") {
        const s = (t.server || "").trim() || inferToolMeta(t.name).mcpServer;
        mcp.add(s);
      }
    }
    const priority = ["duckdb", "storage", "dagster"];
    const ordered = priority.filter((x) => mcp.has(x));
    const rest = [...mcp].filter((x) => !priority.includes(x)).sort((a, b) => a.localeCompare(b));
    const out = [...ordered, ...rest];
    if (inventoryTools.some((t) => t.source === "helper")) out.push("__helpers__");
    if (inventorySkills.length > 0) out.push("__skills__");
    return out;
  }, [inventoryTools, inventorySkills]);

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

  const serverChipLabel = useCallback(
    (key: string) => {
      if (key === "__helpers__") return d.helpersGroup;
      if (key === "__skills__") return d.skillsGroup;
      const pretty: Record<string, string> = { duckdb: "DuckDB", storage: "Storage", dagster: "Dagster" };
      return pretty[key] ?? (key.charAt(0).toUpperCase() + key.slice(1));
    },
    [d.helpersGroup, d.skillsGroup],
  );

  return (
    <aside id={id} className={`dashboard ${className ?? ""}`}>
      <div className="dashboard-header">
        <h2>{d.title}</h2>
        <button type="button" className="btn ghost" onClick={() => void refresh()} disabled={loading}>
          {d.refresh}
        </button>
      </div>

      <section className="dash-card warehouse-panel" aria-label={d.warehouseTitle}>
        <h3>{d.warehouseTitle}</h3>
        <p className="small muted mt0">{d.warehouseHint}</p>
        {(warehouse.status === "error" || warehouse.error) && (
          <p className="error small dash-detail">{warehouse.error ?? "Warehouse unavailable"}</p>
        )}
        <div className="warehouse-layer-stack">
          {(["bronze", "silver", "gold"] as const).map((layer) => {
            const title =
              layer === "bronze" ? d.layerBronze : layer === "silver" ? d.layerSilver : d.layerGold;
            const items = warehouse.layers[layer];
            return (
              <div key={layer} className={`warehouse-layer layer-${layer}`}>
                <div className="warehouse-layer-head">
                  <h4>{title}</h4>
                  <span className="tiny muted">{items.length}</span>
                </div>
                <ul className="warehouse-table-list">
                  {items.length === 0 ? (
                    <li className="tiny muted">{d.emptyLayer}</li>
                  ) : (
                    items.map((t) => (
                      <li key={`${layer}-${t.name}`}>
                        <span className="mono name">{t.name}</span>
                        <span className="warehouse-kind">{t.table_type.replace(/^BASE\s+/i, "")}</span>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            );
          })}
        </div>
        {warehouse.other.length > 0 && (
          <details className="dash-details warehouse-other">
            <summary>
              {d.layerOther} ({warehouse.other.length})
            </summary>
            <ul className="warehouse-table-list tight">
              {warehouse.other.map((t) => (
                <li key={`${t.schema}.${t.name}`}>
                  <span className="mono schema">{t.schema}</span>
                  <span className="mono name">{t.name}</span>
                  <span className="warehouse-kind">{t.table_type.replace(/^BASE\s+/i, "")}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <section className="dash-card mcp-panel" aria-label={d.mcpSectionTitle}>
        <h3>{d.mcpSectionTitle}</h3>
        <dl className="dash-dl compact-status">
          <dt>{d.status}</dt>
          <dd>
            <span className={`pill ${health === "ok" ? "ok" : "bad"}`}>{loading ? "…" : health}</span>
          </dd>
        </dl>
        {healthError && <p className="error small dash-detail">{healthError}</p>}
        <p className="small muted mt0">{d.mcpSectionBlurb}</p>
        {inventoryError && <p className="error small dash-detail">{inventoryError}</p>}

        <div className="mcp-pick-row">
          <span className="tiny muted pick-label">{d.pickServer}</span>
          <div className="mcp-server-chips" role="tablist" aria-label={d.pickServer}>
            {serverGroups.map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={selectedServer === key}
                className={`mcp-server-chip ${selectedServer === key ? "selected" : ""}`}
                onClick={() => setSelectedServer(key)}
              >
                {serverChipLabel(key)}
              </button>
            ))}
          </div>
        </div>

        <p className="tiny muted mcp-tool-count">{d.toolCount(toolsForServer.length)}</p>

        <div className="mcp-tool-cards-grid">
          {toolsForServer.length === 0 ? (
            <p className="small muted mcp-empty">{loading ? "…" : "—"}</p>
          ) : (
            toolsForServer.map((tool) => (
              <article key={tool.name} className="mcp-tool-card">
                <header className="mcp-tool-card-head">
                  <span className="mono mcp-tool-name">{tool.name}</span>
                  <span className={`pill sm cat-${tool.category}`}>{tool.category}</span>
                </header>
                <p className="mcp-tool-desc">{tool.description}</p>
                {tool.sourcePath && (
                  <p className="mcp-tool-path mono tiny muted">
                    {tool.sourcePath}
                  </p>
                )}
                <div className="mcp-tool-example">
                  <span className="tiny muted">{d.exampleUsage}</span>
                  <p className="small muted">{tool.example}</p>
                </div>
              </article>
            ))
          )}
        </div>
      </section>
    </aside>
  );
}
