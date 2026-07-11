import { useCallback, useEffect, useMemo, useState, type ComponentType } from "react";
import type {
  LineageUiResourceResponse,
  SyncConfiguredSource,
  SyncRegistryEntry,
  SyncStatusResponse,
} from "../api";
import { getLineageResource, getSyncStatus, runSync } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

type Props = {
  className?: string;
  id?: string;
  locale: UiLocale;
};

type UiResourceProps = {
  resource: { uri: string; mimeType: string; text?: string; blob?: string };
};

/**
 * Sync & Lineage panel: trigger Quack sync, list registry rows, render MCP-UI lineage.
 *
 * Prefers `@mcp-ui/client` UIResourceRenderer when available; falls back to a sandboxed
 * iframe with the HTML resource text so the panel works without the optional dep.
 */
export function SyncLineagePanel({ className, id, locale }: Props) {
  const t = uiStrings(locale).syncLineage;
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [entries, setEntries] = useState<SyncRegistryEntry[]>([]);
  const [configured, setConfigured] = useState<SyncConfiguredSource[]>([]);
  const [lineage, setLineage] = useState<LineageUiResourceResponse | null>(null);
  const [UiRenderer, setUiRenderer] = useState<ComponentType<UiResourceProps> | null>(null);

  useEffect(() => {
    let cancelled = false;
    void import("@mcp-ui/client")
      .then((mod) => {
        if (cancelled) return;
        const Comp = (mod as { UIResourceRenderer?: ComponentType<UiResourceProps> })
          .UIResourceRenderer;
        if (Comp) {
          setUiRenderer(() => Comp);
        }
      })
      .catch(() => {
        /* optional dependency — iframe fallback */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [status, resource]: [SyncStatusResponse, LineageUiResourceResponse] = await Promise.all([
        getSyncStatus(),
        getLineageResource(),
      ]);
      if (status.error) setError(status.error);
      setEntries(status.entries ?? []);
      setConfigured(status.configured_sources ?? []);
      setLineage(resource);
    } catch (e) {
      setError(String(e));
      setEntries([]);
      setConfigured([]);
      setLineage(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onSync = useCallback(async () => {
    setSyncing(true);
    setNotice(null);
    setError(null);
    try {
      const result = await runSync();
      if (result.status === "error") {
        setError(result.error || t.syncFailed);
      } else {
        setNotice(t.syncOk);
      }
      await refresh();
    } catch (e) {
      setError(`${t.syncFailed}: ${e}`);
    }
    setSyncing(false);
  }, [refresh, t.syncFailed, t.syncOk]);

  const iframeSrcDoc = useMemo(() => lineage?.resource?.text ?? "", [lineage]);

  return (
    <section
      id={id}
      className={`workspace-panel workspace-panel--scroll sync-lineage-view ${className ?? ""}`}
    >
      <header className="section-header section-header--blue sync-lineage-header">
        <div>
          <h2 className="section-title">{t.title}</h2>
          <p className="small muted">{t.hint}</p>
        </div>
        <div className="sync-lineage-actions">
          <button
            type="button"
            className="btn ghost"
            onClick={() => void refresh()}
            disabled={loading || syncing}
          >
            {t.refresh}
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => void onSync()}
            disabled={syncing}
          >
            {syncing ? t.syncing : t.syncNow}
          </button>
        </div>
      </header>

      {error && <p className="error small">{error}</p>}
      {notice && <p className="notice small">{notice}</p>}
      {loading && <p className="muted">{t.loading}</p>}

      <section className="sync-configured" aria-labelledby="sync-configured-heading">
        <h3 id="sync-configured-heading" className="sync-section-title">
          {t.configuredTitle}
        </h3>
        {configured.length === 0 ? (
          <p className="muted small">{t.noConfigured}</p>
        ) : (
          <ul className="sync-configured-list">
            {configured.map((s) => (
              <li key={s.name} className="mono">
                <strong>{s.name}</strong>
                {" → "}
                {s.target_schema}
                {s.table_count != null ? ` · ${s.table_count} tables` : ""}
                <span className="muted"> · {s.uri}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="sync-table-section" aria-labelledby="sync-table-heading">
        <h3 id="sync-table-heading" className="sync-section-title">
          {t.tableTitle}
        </h3>
        {!loading && entries.length === 0 ? (
          <p className="muted">{t.empty}</p>
        ) : (
          <div className="sync-table-wrap">
            <table className="sync-table">
              <thead>
                <tr>
                  <th>{t.colSource}</th>
                  <th>{t.colSourceFqn}</th>
                  <th>{t.colTargetFqn}</th>
                  <th>{t.colRows}</th>
                  <th>{t.colStatus}</th>
                  <th>{t.colSyncedAt}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={`${e.id}-${e.target_fqn}-${e.synced_at}`}>
                    <td className="mono">{e.source_name}</td>
                    <td className="mono">{e.source_fqn}</td>
                    <td className="mono">{e.target_fqn}</td>
                    <td>{e.row_count ?? "—"}</td>
                    <td>
                      <span className={`sync-status sync-status--${e.status}`}>{e.status}</span>
                    </td>
                    <td className="mono small">{e.synced_at ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="sync-lineage-graph" aria-labelledby="sync-lineage-heading">
        <h3 id="sync-lineage-heading" className="sync-section-title">
          {t.lineageTitle}
        </h3>
        <p className="small muted">{t.lineageHint}</p>
        <div className="mcp-ui-host">
          {lineage?.resource && UiRenderer ? (
            <UiRenderer resource={lineage.resource} />
          ) : iframeSrcDoc ? (
            <iframe
              title={t.lineageTitle}
              className="mcp-ui-iframe"
              sandbox="allow-scripts"
              srcDoc={iframeSrcDoc}
            />
          ) : (
            <p className="muted small">{t.empty}</p>
          )}
        </div>
      </section>
    </section>
  );
}
