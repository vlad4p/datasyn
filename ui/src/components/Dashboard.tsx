import { useCallback, useEffect, useState } from "react";
import type { BrainHealth, LlmConfig, PipelineTrace } from "../api";
import {
  getApiDisplayLabel,
  getHealth,
  getLlmConfig,
  isStubHealthResponse,
  probeLlm,
} from "../api";

type Props = { className?: string; pipelineTrace?: PipelineTrace };

export function Dashboard({ className, pipelineTrace }: Props) {
  const [health, setHealth] = useState<string>("—");
  const [healthPayload, setHealthPayload] = useState<BrainHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [llmConfigError, setLlmConfigError] = useState<string | null>(null);
  const [llmProbe, setLlmProbe] = useState<unknown>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pipelineHealth, setPipelineHealth] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setProbeError(null);
    setHealthError(null);
    setLlmConfigError(null);

    try {
      const h = await getHealth();
      setHealthPayload(h);
      setHealth(h.status);
      setPipelineHealth(h.pipeline ?? null);
      try {
        const cfg = await getLlmConfig(h);
        setLlmConfig(cfg);
        setLlmConfigError(null);
      } catch (e) {
        setLlmConfig(null);
        setLlmConfigError(String(e));
      }
    } catch (e) {
      setHealthPayload(null);
      setHealth("error");
      setHealthError(String(e));
      setLlmConfig(null);
      setLlmConfigError(null);
      setPipelineHealth(null);
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
        {!loading && healthPayload && isStubHealthResponse(healthPayload) && (
          <div className="banner warning dash-detail">
            <strong>Incomplete /health</strong> — response is only <code className="inline-code">{"{ \"status\": \"ok\" }"}</code>
            . Vite may be proxying to the wrong host/port (e.g. an old uvicorn on{" "}
            <code className="inline-code">127.0.0.1:8000</code>). This project maps the Docker brain to{" "}
            <code className="inline-code">127.0.0.1:8002</code> — check <code className="inline-code">VITE_PROXY_TARGET</code> in{" "}
            <code className="inline-code">vite.config.ts</code> and <code className="inline-code">docker-compose.yaml</code>{" "}
            <code className="inline-code">8002:8000</code>. Or set <code className="inline-code">VITE_API_BASE</code> to the brain
            that returns full <code className="inline-code">GET /health</code> JSON.
          </div>
        )}
        {healthError && (
          <p className="error small dash-detail">
            {healthError}
            <span className="block muted tiny mt">
              Ensure <code className="inline-code">docker compose up brain</code> publishes{" "}
              <code className="inline-code">8002:8000</code>
              , then <code className="inline-code">curl http://127.0.0.1:8002/health</code>. The UI calls the brain via
              Vite&apos;s <code className="inline-code">/api</code> proxy by default (no Docker DNS in the browser). If
              you set <code className="inline-code">VITE_API_BASE</code> to a direct URL, add matching origins to{" "}
              <code className="inline-code">CORS_EXTRA_ORIGINS</code> on the brain when the UI origin is not localhost.
            </span>
          </p>
        )}
      </section>

      <section className="dash-card">
        <h3>Pipeline (debug)</h3>
        <p className="small muted">
          From <code className="inline-code">GET /api/health</code> → <code className="inline-code">pipeline</code> (who
          lists <code className="inline-code">/data-local</code>, MCP URLs, <code className="inline-code">
            DATACYBER_PIPELINE_DEBUG
          </code>
          ). Rebuild the brain if this is empty.
        </p>
        {pipelineHealth ? (
          <pre className="dash-json">{JSON.stringify(pipelineHealth, null, 2)}</pre>
        ) : (
          <p className="muted">—</p>
        )}
      </section>

      {pipelineTrace && (
        <section className="dash-card">
          <h3>Last chat</h3>
          <p className="mono small muted">
            request_id: {pipelineTrace.requestId}
            <br />
            at: {new Date(pipelineTrace.at).toISOString()}
          </p>
          {pipelineTrace.debug ? (
            <pre className="dash-json mt">{JSON.stringify(pipelineTrace.debug, null, 2)}</pre>
          ) : (
            <p className="small muted mt">
              Set <code className="inline-code">DATACYBER_PIPELINE_DEBUG=1</code> on the brain and restart to include
              step timings, tool names, and message timeline in this panel.
            </p>
          )}
        </section>
      )}

      <section className="dash-card">
        <h3>LLM (config)</h3>
        <p className="small muted dash-detail">
          The browser <strong>never</strong> sends your LiteLLM key. Chat goes to the brain only; the brain calls LiteLLM.
          If chat shows <code className="inline-code">401 … Received API Key = sk-…XXXX</code>, that suffix is whatever
          the <strong>brain process</strong> has loaded — compare to <code className="inline-code">
            litellm_key_suffix
          </code>{" "}
          below. If it does not match your repo <code className="inline-code">.env</code>, recreate the brain:{" "}
          <code className="inline-code">docker compose up -d --force-recreate brain</code>.
        </p>
        {llmConfigError && (
          <p className="error small dash-detail">
            {llmConfigError}
          </p>
        )}
        {llmConfig ? (
          <>
            <dl className="dash-summary">
              <div>
                <dt>LiteLLM base (brain)</dt>
                <dd className="mono">{llmConfig.litellm_base ?? "—"}</dd>
              </div>
              <div>
                <dt>CHAT_MODEL</dt>
                <dd className="mono">{llmConfig.chat_model || "—"}</dd>
              </div>
              <div>
                <dt>Key suffix (LITELLM_KEY)</dt>
                <dd className="mono">{llmConfig.litellm_key_suffix ?? "—"}</dd>
              </div>
              <div>
                <dt>Brain in Docker</dt>
                <dd>{llmConfig.in_docker ? "yes" : "no"}</dd>
              </div>
              <div>
                <dt>OPENAI_API_KEY in process</dt>
                <dd>
                  {llmConfig.openai_api_key_env_set
                    ? `set (suffix …${llmConfig.openai_api_key_env_suffix ?? "?"})`
                    : "unset"}
                </dd>
              </div>
            </dl>
            <details className="dash-details">
              <summary>Raw JSON</summary>
              <pre className="dash-json mt">{JSON.stringify(llmConfig, null, 2)}</pre>
            </details>
          </>
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
