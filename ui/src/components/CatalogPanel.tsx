import { useCallback, useEffect, useState } from "react";
import { getCatalogDatasets, type CatalogDatasetSummary } from "../api";

type Props = { className?: string };

function formatWhen(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function CatalogPanel({ className }: Props) {
  const [rows, setRows] = useState<CatalogDatasetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const data = await getCatalogDatasets({ limit: 60 });
      setRows(data);
    } catch (e) {
      setErr(String(e));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <aside className={`catalog-panel ${className ?? ""}`} aria-label="Data catalog">
      <div className="catalog-panel-header">
        <h2>Catalog</h2>
        <button type="button" className="btn ghost" onClick={() => void load()} disabled={loading}>
          Refresh
        </button>
      </div>
      <p className="catalog-hint muted small">
        OpenMetadata-style datasets (FQN, service, schema). <strong>Refresh</strong> calls the brain{" "}
        <code className="inline-code">GET /catalog/datasets</code>, which runs the MCP tool{" "}
        <code className="inline-code">catalog_list_datasets</code>. Register rows via{" "}
        <code className="inline-code">catalog_register_or_update_dataset</code>.
      </p>

      {err && <div className="banner error catalog-error">{err}</div>}

      {loading && rows.length === 0 && !err && <p className="muted small catalog-loading">Loading…</p>}

      {!loading && rows.length === 0 && !err && (
        <p className="muted small catalog-empty">No datasets yet. Ask the agent to register tables after ingest.</p>
      )}

      <div className="catalog-cards">
        {rows.map((d) => (
          <article key={d.fullyQualifiedName ?? d.id ?? d.name} className="catalog-card">
            <div className="catalog-card-top">
              <span className="catalog-type pill">{d.tableType || "Table"}</span>
              <span className="catalog-meta muted tiny">{formatWhen(d.updatedAt)}</span>
            </div>
            <h3 className="catalog-title">{d.displayName || d.name || "—"}</h3>
            <p className="catalog-fqn mono">{d.fullyQualifiedName || "—"}</p>
            {(d.service?.name || d.schema?.name) && (
              <p className="catalog-loc small">
                {[d.service?.name, d.database?.name, d.schema?.name].filter(Boolean).join(" · ")}
              </p>
            )}
            {d.description ? <p className="catalog-desc small">{d.description}</p> : null}
            <div className="catalog-stats tiny muted">
              {typeof d.columnCount === "number" ? <span>{d.columnCount} columns</span> : null}
              {typeof d.tagCount === "number" && d.tagCount > 0 ? <span>{d.tagCount} tags</span> : null}
            </div>
          </article>
        ))}
      </div>
    </aside>
  );
}
