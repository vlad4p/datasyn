import { useCallback, useEffect, useState } from "react";
import type { BrainHealth } from "../api";
import { getHealth, getLlmModels, probeLlm, setChatModel, setLitellmKey, clearLitellmKey } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";
import { ModelSwitch, LLM_CONFIG_CHANGED_EVENT, readStoredChatModel } from "./ModelSwitch";

type Props = {
  id?: string;
  className?: string;
  locale: UiLocale;
  onConfigChange?: (health: BrainHealth) => void;
  llmConfigRevision?: number;
};

export function AgentConfigPanel({
  id,
  className,
  locale,
  onConfigChange,
  llmConfigRevision = 0,
}: Props) {
  const c = uiStrings(locale).agentConfig;
  const [health, setHealth] = useState<BrainHealth | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState(false);
  const [resettingKey, setResettingKey] = useState(false);
  const [probing, setProbing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const h = await getHealth();
      setHealth(h);
      onConfigChange?.(h);
    } catch (e) {
      setError(String(e));
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, [onConfigChange]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    void getHealth().then(async (h) => {
      if (cancelled) return;
      const stored = readStoredChatModel();
      const current = (h.chat_model || "").trim();
      const canRestore =
        stored &&
        stored !== current &&
        ((h.model_provider === "openrouter" && h.has_openrouter_key) ||
          (h.model_provider === "litellm" && h.has_key));
      if (!canRestore) return;
      try {
        const updated = await setChatModel(stored);
        if (cancelled) return;
        setHealth((prev) =>
          prev ? { ...prev, chat_model: updated.chat_model, chat_model_source: "runtime" } : prev,
        );
      } catch {
        /* keep env/default model */
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const saveKey = async () => {
    const trimmed = keyInput.trim();
    if (!trimmed) {
      setError(c.keyRequired);
      return;
    }
    setSavingKey(true);
    setError(null);
    setProbeResult(null);
    try {
      const res = await setLitellmKey(trimmed);
      const probe = (await probeLlm()) as Record<string, unknown>;
      if (probe.ok !== true) {
        await clearLitellmKey();
        const hint = typeof probe.hint === "string" ? probe.hint : null;
        const err =
          typeof probe.body_preview === "string"
            ? probe.body_preview.slice(0, 200)
            : typeof probe.error === "string"
              ? probe.error
              : c.keyInvalid;
        setError(hint ?? err);
        await refresh();
        return;
      }
      setHealth((prev) =>
        prev
          ? {
              ...prev,
              has_key: res.has_key,
              litellm_key_suffix: res.litellm_key_suffix ?? prev.litellm_key_suffix,
              litellm_key_source: res.litellm_key_source ?? "runtime",
            }
          : prev,
      );
      setKeyInput("");
      window.dispatchEvent(new CustomEvent(LLM_CONFIG_CHANGED_EVENT));
      const catalog = await getLlmModels({ refresh: true });
      const n = catalog.status === "ok" ? (catalog.count ?? catalog.models?.length ?? 0) : 0;
      setProbeResult(
        catalog.status === "ok"
          ? `${c.probeOk} ${c.modelsListed.replace("{count}", String(n))}`
          : catalog.error ?? c.keyInvalid,
      );
      onConfigChange?.({
        ...(health ?? { status: "ok" }),
        has_key: res.has_key,
        litellm_key_suffix: res.litellm_key_suffix,
        litellm_key_source: res.litellm_key_source,
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setSavingKey(false);
    }
  };

  const resetKey = async () => {
    setResettingKey(true);
    setError(null);
    setProbeResult(null);
    try {
      const res = await clearLitellmKey();
      setKeyInput("");
      window.dispatchEvent(new CustomEvent(LLM_CONFIG_CHANGED_EVENT));
      setHealth((prev) =>
        prev
          ? {
              ...prev,
              has_key: res.has_key,
              litellm_key_suffix: res.litellm_key_suffix ?? prev.litellm_key_suffix,
              litellm_key_source: res.litellm_key_source ?? "env",
            }
          : prev,
      );
      onConfigChange?.({
        ...(health ?? { status: "ok" }),
        has_key: res.has_key,
        litellm_key_suffix: res.litellm_key_suffix,
        litellm_key_source: res.litellm_key_source,
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setResettingKey(false);
    }
  };

  const runProbe = async () => {
    setProbing(true);
    setError(null);
    setProbeResult(null);
    try {
      const raw = (await probeLlm()) as Record<string, unknown>;
      if (raw.ok === true) {
        setProbeResult(c.probeOk);
      } else {
        const hint = typeof raw.hint === "string" ? raw.hint : null;
        const err = typeof raw.error === "string" ? raw.error : JSON.stringify(raw).slice(0, 400);
        setProbeResult(hint ? `${err} — ${hint}` : err);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setProbing(false);
    }
  };

  const provider = health?.model_provider ?? "—";
  const isLitellm = provider === "litellm";

  return (
    <section
      id={id}
      className={`agent-config-panel workspace-panel ${className ?? ""}`}
      aria-label={c.title}
    >
      <header className="agent-config-panel__header">
        <h2 className="section-title">{c.title}</h2>
        <p className="small muted">{c.hint}</p>
      </header>

      {loading && <p className="small muted">{c.loading}</p>}
      {error && <p className="error small">{error}</p>}

      {!loading && health && (
        <div className="agent-config-panel__grid">
          <dl className="dash-dl agent-config-dl">
            <dt>{c.provider}</dt>
            <dd>
              <span className="mono">{provider}</span>
            </dd>
            {isLitellm && (
              <>
                <dt>{c.proxyBase}</dt>
                <dd className="mono">{health.litellm_base || "—"}</dd>
                <dt>{c.keyStatus}</dt>
                <dd>
                  {health.has_key ? (
                    <span className="pill sm ok">
                      {c.keyConfigured}
                      {health.litellm_key_suffix ? ` …${health.litellm_key_suffix}` : ""}
                      {health.litellm_key_source === "runtime" ? ` (${c.runtime})` : ""}
                    </span>
                  ) : (
                    <span className="pill sm bad">{c.keyMissing}</span>
                  )}
                </dd>
              </>
            )}
            <dt>{c.chatModel}</dt>
            <dd>
              <ModelSwitch
                locale={locale}
                modelProvider={health.model_provider}
                hasOpenRouterKey={health.has_openrouter_key}
                hasLitellmKey={health.has_key}
                litellmBase={health.litellm_base}
                configRevision={llmConfigRevision}
                chatModel={health.chat_model ?? "—"}
                onModelChange={(modelId) =>
                  setHealth((prev) =>
                    prev ? { ...prev, chat_model: modelId, chat_model_source: "runtime" } : prev,
                  )
                }
              />
            </dd>
          </dl>

          {isLitellm && (
            <form
              className="agent-config-form"
              onSubmit={(e) => {
                e.preventDefault();
                void saveKey();
              }}
            >
              <label className="agent-config-form__label" htmlFor="litellm-key-input">
                {c.virtualKeyLabel}
              </label>
              <p className="small muted">{c.virtualKeyHint}</p>
              <input
                id="litellm-key-input"
                type="password"
                className="agent-config-form__input"
                autoComplete="off"
                placeholder={c.virtualKeyPlaceholder}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                disabled={savingKey}
              />
              <div className="agent-config-form__actions">
                <button type="submit" className="btn primary" disabled={savingKey || !keyInput.trim()}>
                  {savingKey ? c.saving : c.saveKey}
                </button>
                <button
                  type="button"
                  className="btn ghost"
                  disabled={resettingKey || health.litellm_key_source !== "runtime"}
                  onClick={() => void resetKey()}
                  title={c.resetKey}
                >
                  {resettingKey ? c.resetting : c.resetKey}
                </button>
                <button
                  type="button"
                  className="btn ghost"
                  disabled={probing || !health.has_key}
                  onClick={() => void runProbe()}
                >
                  {probing ? c.probing : c.testConnection}
                </button>
                <button type="button" className="btn ghost" onClick={() => void refresh()} disabled={loading}>
                  {c.refresh}
                </button>
              </div>
              {probeResult && <p className="small agent-config-probe">{probeResult}</p>}
            </form>
          )}

          {!isLitellm && (
            <p className="small muted">{c.notLitellmHint.replace("{provider}", provider)}</p>
          )}
        </div>
      )}
    </section>
  );
}
