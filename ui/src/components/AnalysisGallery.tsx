import { useCallback, useEffect, useState } from "react";
import type { AnalysisDetailResponse, AnalysisManifest, AnalysesListResponse } from "../api";
import { getAnalysis, listAnalyses } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";
import { MarkdownMessage } from "./MarkdownMessage";

type Props = {
  className?: string;
  id?: string;
  locale: UiLocale;
  refreshToken?: number;
};

export function AnalysisGallery({ className, id, locale, refreshToken = 0 }: Props) {
  const a = uiStrings(locale).analyses;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [list, setList] = useState<AnalysisManifest[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AnalysisDetailResponse | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: AnalysesListResponse = await listAnalyses();
      setList(data.analyses ?? []);
    } catch (e) {
      setError(String(e));
      setList([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshToken]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    getAnalysis(selectedId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [selectedId]);

  if (selectedId && detail) {
    const m = detail.manifest;
    return (
      <section id={id} className={`workspace-panel workspace-panel--scroll ${className ?? ""}`}>
        <div className="analysis-detail">
          <div className="analysis-detail-header">
            <div>
              <h2 className="section-title">{m.title}</h2>
              <p className="small muted">
                {formatDate(m.created_at, locale)}
                {m.dataset_fqn ? ` · ${m.dataset_fqn}` : ""}
              </p>
            </div>
            <button type="button" className="btn ghost" onClick={() => setSelectedId(null)}>
              {a.back}
            </button>
          </div>
          <MarkdownMessage role="assistant" content={detail.report_md} />
        </div>
      </section>
    );
  }

  return (
    <section id={id} className={`workspace-panel workspace-panel--scroll ${className ?? ""}`}>
      <h2 className="section-title">{a.title}</h2>
      <p className="small muted">{a.hint}</p>
      {error && <p className="error small">{error}</p>}
      {loading && <p className="muted">{a.loading}</p>}
      {!loading && list.length === 0 && (
        <div className="empty-state">
          <p>{a.empty}</p>
        </div>
      )}
      <div className="analysis-grid">
        {list.map((item) => (
          <button
            key={item.id}
            type="button"
            className="analysis-card"
            onClick={() => setSelectedId(item.id)}
          >
            <h3>{item.title}</h3>
            <p className="analysis-card-date">{formatDate(item.created_at, locale)}</p>
            {item.dataset_fqn && (
              <p className="mono small" style={{ margin: "0 0 0.35rem" }}>
                {item.dataset_fqn}
              </p>
            )}
            <p className="analysis-card-preview">{item.preview}</p>
            <p className="tiny muted">
              {a.messageCount(item.message_count)}
            </p>
          </button>
        ))}
      </div>
    </section>
  );
}

function formatDate(iso: string, locale: UiLocale): string {
  try {
    return new Date(iso).toLocaleString(locale === "es" ? "es" : "en");
  } catch {
    return iso;
  }
}
