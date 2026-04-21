import { useCallback, useEffect, useState } from "react";
import { getApiDisplayLabel, getHealth, getLlmConfig, probeLlm } from "../api";

type Props = { className?: string };

export function Dashboard({ className }: Props) {
  const [health, setHealth] = useState<string>("—");
  const [healthError, setHealthError] = useState<string | null>(null);
  const [llmConfig, setLlmConfig] = useState<Record<string, unknown> | null>(null);
  const [llmConfigError, setLlmConfigError] = useState<string | null>(null);
  const [llmProbe, setLlmProbe] = useState<unknown>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setProbeError(null);
    setHealthError(null);
    setLlmConfigError(null);

    try {
      const h = await getHealth();
      setHealth(h.status);
      try {
        const cfg = await getLlmConfig(h);
        setLlmConfig(cfg as unknown as Record<string, unknown>);
        setLlmConfigError(null);
      } catch (e) {
        setLlmConfig(null);
        setLlmConfigError(String(e));
      }
    } catch (e) {
      setHealth("error");
      setHealthError(String(e));
      setLlmConfig(null);
      setLlmConfigError(null);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runProbe = async () => {
    setProbeError(null);
    setLlmProbe(null);
    try {
      const j = await probeLlm();
      setLlmProbe(j);
    } catch (e) {
      setProbeError(String(e));
    }
  };

  return (
    <aside className={`dashboard ${className ?? ""}`}>
      <div className="dashboard-header">
        <h2>Dashboard</h2>
        <button type="button" className="btn ghost" onClick={() => void refresh()} disabled={loading}>
          Refresh
        </button>
      </div>

      <section className="dash-card">
        <h3>API</h3>
        <p className="mono muted">{getApiDisplayLabel()}</p>
        <dl className="dash-dl">
          <dt>Brain</dt>
          <dd>
            <span className={`pill ${health === "ok" ? "ok" : "bad"}`}>{loading ? "…" : health}</span>
          </dd>
        </dl>
        {healthError && (
          <p className="error small dash-detail">
            {healthError}
            <span className="block muted tiny mt">
              Ensure <code className="inline-code">docker compose up brain</code> maps <code className="inline-code">
                8000:8000
              </code>
              , then <code className="inline-code">curl http://127.0.0.1:8000/health</code>. The UI calls the brain via
              Vite&apos;s <code className="inline-code">/api</code> proxy by default (no Docker DNS in the browser). If
              you set <code className="inline-code">VITE_API_BASE</code> to a direct URL, add matching origins to{" "}
              <code className="inline-code">CORS_EXTRA_ORIGINS</code> on the brain when the UI origin is not localhost.
            </span>
          </p>
        )}
      </section>

      <section className="dash-card">
        <h3>LLM (config)</h3>
        {llmConfigError && (
          <p className="error small dash-detail">
            {llmConfigError}
          </p>
        )}
        {llmConfig ? (
          <pre className="dash-json">{JSON.stringify(llmConfig, null, 2)}</pre>
        ) : !llmConfigError ? (
          <p className="muted">—</p>
        ) : null}
        <button type="button" className="btn secondary" onClick={() => void runProbe()}>
          Probe LiteLLM (GET /health/llm)
        </button>
        {probeError && <p className="error small">{probeError}</p>}
        {llmProbe !== null && (
          <pre className="dash-json mt">{JSON.stringify(llmProbe, null, 2)}</pre>
        )}
      </section>

      <section className="dash-card hints">
        <h3>Rendering</h3>
        <p className="small muted">
          Markdown <strong>tables</strong>; fenced <strong>Mermaid</strong> (<code className="inline-code">mermaid</code>
          ); <strong>Vega-Lite</strong> (<code className="inline-code">vega-lite</code> JSON or Vega-Lite in{" "}
          <code className="inline-code">json</code> blocks); JSON arrays → data tables; <code className="inline-code">
            https
          </code>{" "}
          / <code className="inline-code">data:image/…</code> images. Paths under <code className="inline-code">
            /project/…
          </code>{" "}
          (reports, PNG/MD) are mapped to <code className="inline-code">GET /artifacts/file</code> on the brain. Lists of{" "}
          <code className="inline-code">Name: N cases</code> lines may get an extra bar chart.
        </p>
      </section>
    </aside>
  );
}
