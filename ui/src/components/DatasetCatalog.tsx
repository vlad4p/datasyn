import { useCallback, useEffect, useMemo, useState } from "react";
import type { CatalogDatasetCard, CatalogDatasetDetailResponse, CatalogDatasetsResponse } from "../api";
import { getCatalogDatasetDetail, getCatalogDatasets } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";
import { LayerBadge } from "./ui/LayerBadge";
import { SystemToolsPanel } from "./SystemToolsPanel";

type LayerFilter = "all" | "bronze" | "silver" | "gold";

type Props = {
  className?: string;
  id?: string;
  locale: UiLocale;
  onAnalyzeDataset?: (fqn: string) => void;
};

function LineageList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="lineage-block">
      <h4>{title}</h4>
      <ul className="lineage-list">
        {items.map((k) => (
          <li key={k} className="mono">
            {k}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DatasetCatalog({ className, id, locale, onAnalyzeDataset }: Props) {
  const c = uiStrings(locale).catalog;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<CatalogDatasetsResponse | null>(null);
  const [layer, setLayer] = useState<LayerFilter>("all");
  const [duckdbTable, setDuckdbTable] = useState<string>("");
  const [search, setSearch] = useState("");
  const [selectedFqn, setSelectedFqn] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogDatasetDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getCatalogDatasets({
        duckdbTable: duckdbTable || null,
      });
      setPayload(data);
    } catch (e) {
      setError(String(e));
      setPayload(null);
    }
    setLoading(false);
  }, [duckdbTable]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selectedFqn) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    getCatalogDatasetDetail(selectedFqn)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedFqn]);

  const warehouseTables = payload?.warehouse_tables ?? [];

  const filtered = useMemo(() => {
    const list = payload?.datasets ?? [];
    const q = search.trim().toLowerCase();
    return list.filter((d) => {
      if (layer !== "all" && d.layer !== layer) return false;
      if (!q) return true;
      const hay = [
        d.fqn,
        d.name,
        d.description ?? "",
        d.dagster_asset_key ?? "",
        ...(d.tags ?? []),
        ...(d.lineage_upstream ?? []),
        ...(d.lineage_downstream ?? []),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [layer, payload?.datasets, search]);

  const statusHints: string[] = [];
  if (payload?.dagster_status === "unavailable") statusHints.push(c.dagsterUnavailable);
  else if (payload?.dagster_status === "ok") statusHints.push(c.dagsterOk);
  if (payload?.dagster_error) statusHints.push(payload.dagster_error);
  if (payload?.catalog_status === "unavailable") statusHints.push(c.catalogUnavailable);
  else if (payload?.catalog_status === "ok") statusHints.push(c.catalogOk);

  const analyzeFqn =
    selectedFqn && !selectedFqn.startsWith("dagster/") ? selectedFqn : null;

  return (
    <section id={id} className={`workspace-panel workspace-panel--scroll ${className ?? ""}`}>
      <h2 className="section-title">{c.title}</h2>
      <p className="small muted">{c.hint}</p>
      {payload?.dagster_graphql_url && (
        <p className="tiny muted">
          Dagster GraphQL: {payload.dagster_graphql_url}
        </p>
      )}
      {statusHints.map((h) => (
        <p key={h} className="small muted">
          {h}
        </p>
      ))}
      {error && <p className="error small">{error}</p>}

      <div className="catalog-toolbar">
        <input
          type="search"
          className="catalog-search"
          placeholder={c.searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label={c.searchPlaceholder}
        />
        <label className="catalog-select-wrap">
          <span className="tiny muted">{c.filterDuckdbTable}</span>
          <select
            className="catalog-select"
            value={duckdbTable}
            onChange={(e) => setDuckdbTable(e.target.value)}
            aria-label={c.filterDuckdbTable}
          >
            <option value="">{c.filterDuckdbAll}</option>
            {warehouseTables.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <div className="schema-chips" role="group" aria-label={c.filterLabel}>
          {(["all", "bronze", "silver", "gold"] as const).map((l) => (
            <button
              key={l}
              type="button"
              className={`schema-chip layer-${l} ${layer === l ? "is-active" : ""}`}
              onClick={() => setLayer(l)}
            >
              {l === "all"
                ? c.filterAll
                : l === "bronze"
                  ? c.filterBronze
                  : l === "silver"
                    ? c.filterSilver
                    : c.filterGold}
            </button>
          ))}
        </div>
        <button type="button" className="btn ghost" onClick={() => void refresh()} disabled={loading}>
          {c.refresh}
        </button>
      </div>

      {loading && <p className="muted">{c.loading}</p>}
      {!loading && filtered.length === 0 && (
        <div className="empty-state">
          <p>{c.empty}</p>
        </div>
      )}

      <div className="dataset-grid">
        {filtered.map((d) => (
          <DatasetCard key={d.fqn} dataset={d} locale={locale} onClick={() => setSelectedFqn(d.fqn)} />
        ))}
      </div>

      {selectedFqn && (
        <>
          <div className="catalog-drawer-backdrop" onClick={() => setSelectedFqn(null)} aria-hidden />
          <aside className="catalog-drawer" role="dialog" aria-label={c.detailTitle}>
            <button type="button" className="btn ghost" onClick={() => setSelectedFqn(null)}>
              {c.close}
            </button>
            <h2>{selectedFqn}</h2>
            {detailLoading && <p className="muted">{c.loading}</p>}
            {detail?.dataset && (
              <>
                <LayerBadge
                  layer={
                    (detail.dataset.layer === "bronze" ||
                    detail.dataset.layer === "silver" ||
                    detail.dataset.layer === "gold"
                      ? detail.dataset.layer
                      : "other") as "bronze" | "silver" | "gold" | "other"
                  }
                />
                {detail.dataset.description && (
                  <p className="small" style={{ marginTop: "0.75rem" }}>
                    {detail.dataset.description}
                  </p>
                )}
                <div className="dataset-card-meta" style={{ marginTop: "0.5rem" }}>
                  {detail.dataset.in_warehouse && <span className="badge-pill warehouse">DuckDB</span>}
                  {detail.dataset.in_catalog && <span className="badge-pill catalog">Postgres</span>}
                  {detail.dataset.in_dagster && (
                    <span className="badge-pill dagster">Dagster</span>
                  )}
                </div>
                {detail.dataset.dagster_asset_key && (
                  <p className="small muted">
                    {c.dagsterAsset}: <span className="mono">{detail.dataset.dagster_asset_key}</span>
                  </p>
                )}
                {(detail.dataset.dagster_jobs ?? []).length > 0 && (
                  <p className="small muted">
                    {c.dagsterJob}: {(detail.dataset.dagster_jobs ?? []).join(", ")}
                  </p>
                )}
              </>
            )}

            <h3 className="lineage-section-title">{c.lineageTitle}</h3>
            {detail?.lineage &&
            (detail.lineage.upstream?.length || detail.lineage.downstream?.length) ? (
              <>
                <LineageList title={c.lineageUpstream} items={detail.lineage.upstream ?? []} />
                <LineageList title={c.lineageDownstream} items={detail.lineage.downstream ?? []} />
              </>
            ) : (
              !detailLoading && <p className="small muted">{c.lineageEmpty}</p>
            )}

            {detail?.catalog_columns && detail.catalog_columns.length > 0 && (
              <>
                <h3 style={{ marginTop: "1rem" }}>{c.columnsCatalog}</h3>
                <ul className="warehouse-table-list tight">
                  {detail.catalog_columns.map((col) => (
                    <li key={col.name}>
                      <span className="mono name">{col.name}</span>
                      <span className="warehouse-kind">{col.type}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {detail?.warehouse_columns && detail.warehouse_columns.length > 0 && (
              <>
                <h3 style={{ marginTop: "1rem" }}>{c.columnsWarehouse}</h3>
                <ul className="warehouse-table-list tight">
                  {detail.warehouse_columns.map((col) => (
                    <li key={col.name}>
                      <span className="mono name">{col.name}</span>
                      <span className="warehouse-kind">{col.type}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {onAnalyzeDataset && analyzeFqn && (
              <button
                type="button"
                className="btn primary"
                style={{ marginTop: "1rem" }}
                onClick={() => {
                  onAnalyzeDataset(analyzeFqn);
                  setSelectedFqn(null);
                }}
              >
                {c.analyzeInAgent}
              </button>
            )}
          </aside>
        </>
      )}

      <details className="system-tools-panel">
        <summary>{c.systemTools}</summary>
        <SystemToolsPanel locale={locale} />
      </details>
    </section>
  );
}

function DatasetCard({
  dataset: d,
  locale,
  onClick,
}: {
  dataset: CatalogDatasetCard;
  locale: UiLocale;
  onClick: () => void;
}) {
  const c = uiStrings(locale).catalog;
  const layer = (d.layer === "bronze" || d.layer === "silver" || d.layer === "gold" ? d.layer : "other") as
    | "bronze"
    | "silver"
    | "gold"
    | "other";
  const up = d.lineage_upstream?.length ?? 0;
  const down = d.lineage_downstream?.length ?? 0;

  return (
    <button type="button" className={`dataset-card layer-${layer}`} onClick={onClick}>
      <div className="dataset-card-head">
        <h3>{d.name}</h3>
        <LayerBadge layer={layer} />
      </div>
      <p className="dataset-card-fqn mono">{d.fqn}</p>
      {d.dagster_asset_key && (
        <p className="tiny muted mono">
          {c.dagsterAsset}: {d.dagster_asset_key}
        </p>
      )}
      <p className="dataset-card-desc">{d.description || c.noDescription}</p>
      <div className="dataset-card-meta">
        {d.column_count != null && (
          <span className="badge-pill">
            {c.columns}: {d.column_count}
          </span>
        )}
        {d.in_warehouse && <span className="badge-pill warehouse">DuckDB</span>}
        {d.in_catalog && <span className="badge-pill catalog">Postgres</span>}
        {d.in_dagster && <span className="badge-pill dagster">Dagster</span>}
        {(up > 0 || down > 0) && (
          <span className="badge-pill lineage">
            ↑{up} ↓{down}
          </span>
        )}
      </div>
    </button>
  );
}
