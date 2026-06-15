import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BrainHealth } from "../api";
import { getHealth, setChatModel } from "../api";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";
import { MarkdownMessage } from "./MarkdownMessage";
import { ModelSwitch, LLM_CONFIG_CHANGED_EVENT, readStoredChatModel } from "./ModelSwitch";
import type { ChatMsg } from "../types/chat";

export type { ChatMsg };

type Props = {
  className?: string;
  id?: string;
  locale: UiLocale;
  messages: ChatMsg[];
  input: string;
  setInput: (v: string) => void;
  busy: boolean;
  error: string | null;
  notice?: string | null;
  onSend: () => void;
  onExportAnalysis?: () => void;
  exporting?: boolean;
  llmConfigRevision?: number;
};

export function AgentChatPanel({
  className,
  id,
  locale,
  messages,
  input,
  setInput,
  busy,
  error,
  notice,
  onSend,
  onExportAnalysis,
  exporting = false,
  llmConfigRevision = 0,
}: Props) {
  const s = uiStrings(locale);
  const feedRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [health, setHealth] = useState<BrainHealth | null>(null);

  useEffect(() => {
    getHealth()
      .then(async (h) => {
        setHealth(h);
        const stored = readStoredChatModel();
        const current = (h.chat_model || "").trim();
        if (
          stored &&
          stored !== current &&
          ((h.model_provider === "openrouter" && h.has_openrouter_key) ||
            (h.model_provider === "litellm" && h.has_key))
        ) {
          try {
            const updated = await setChatModel(stored);
            setHealth((prev) => (prev ? { ...prev, chat_model: updated.chat_model } : prev));
          } catch {
            /* keep env/default model */
          }
        }
      })
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    const refresh = () => {
      void getHealth()
        .then(setHealth)
        .catch(() => setHealth(null));
    };
    window.addEventListener(LLM_CONFIG_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(LLM_CONFIG_CHANGED_EVENT, refresh);
  }, []);

  const last = messages[messages.length - 1];
  const footerThinking = busy && !(last?.role === "assistant" && last?.streaming === true);
  const canExport = messages.some((m) => m.role === "assistant" && (m.content || "").trim());

  useEffect(() => {
    const root = feedRef.current;
    const target = endRef.current;
    if (!root || !target) return;
    const io = new IntersectionObserver(
      (entries) => {
        stickToBottomRef.current = entries[0]?.isIntersecting ?? true;
      },
      { root, rootMargin: "0px 0px 96px 0px", threshold: 0 },
    );
    io.observe(target);
    return () => io.disconnect();
  }, [messages.length, footerThinking]);

  useEffect(() => {
    const el = feedRef.current;
    if (!el || !stickToBottomRef.current) return;
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    });
    return () => cancelAnimationFrame(id);
  }, [messages, busy, footerThinking]);

  const modelLabel = health?.chat_model ?? "—";
  const statusOk = health?.status === "ok";

  return (
    <section id={id} className={`chat-panel workspace-panel ${className ?? ""}`} aria-label={s.chatAria}>
      <header className="agent-chat-header">
        <div className="agent-identity">
          <span className="agent-avatar" aria-hidden />
          <div className="agent-identity-text">
            <h2>{s.agentTitle}</h2>
            <ModelSwitch
              locale={locale}
              modelProvider={health?.model_provider}
              hasOpenRouterKey={health?.has_openrouter_key}
              hasLitellmKey={health?.has_key}
              litellmBase={health?.litellm_base}
              configRevision={llmConfigRevision}
              chatModel={modelLabel}
              disabled={busy}
              onModelChange={(modelId) =>
                setHealth((prev) => (prev ? { ...prev, chat_model: modelId } : prev))
              }
            />
          </div>
          <span
            className={`agent-status-dot ${statusOk ? "" : "error"}`}
            title={statusOk ? s.agentOnline : s.agentOffline}
            aria-hidden
          />
        </div>
        <div className="agent-actions">
          {onExportAnalysis && (
            <button
              type="button"
              className="btn ghost"
              disabled={!canExport || busy || exporting}
              onClick={onExportAnalysis}
            >
              {exporting ? s.exporting : s.exportAnalysis}
            </button>
          )}
        </div>
      </header>

      <div className="chat-panel-inner">
        <div ref={feedRef} className="chat-transcript">
          {messages.length === 0 && (
            <div className="empty">
              <div className="empty-intro-md">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.chatEmpty}</ReactMarkdown>
              </div>
              <div className="suggestions">
                {s.suggestions.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="chip"
                    onClick={() => setInput(q)}
                    disabled={busy}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => {
            if (m.role === "user") {
              return (
                <div key={m.id} className="message-turn message-turn--user">
                  <MarkdownMessage role="user" content={m.content} />
                </div>
              );
            }
            return (
              <div key={m.id} className="message-turn message-turn--assistant">
                <div className="assistant-turn">
                  {m.activity && m.streaming && (
                    <div className="stream-thoughts" aria-live="polite">
                      <div className="stream-thoughts-head">
                        <span className="stream-thoughts-pulse" aria-hidden />
                        <span className="stream-thoughts-title">{s.streamThinkingTitle}</span>
                      </div>
                      <p className="stream-thoughts-body">{m.activity}</p>
                    </div>
                  )}
                  {(m.subagentContent || "").length > 0 && (
                    <div className="subagent-wrap">
                      <div className="subagent-header">
                        <span className="subagent-badge" aria-hidden />
                        {s.subagentLabel}
                      </div>
                      <MarkdownMessage role="assistant" variant="subagent" content={m.subagentContent ?? ""} />
                    </div>
                  )}
                  {m.content ? (
                    <MarkdownMessage role="assistant" content={m.content} />
                  ) : m.streaming ? (
                    <div className="bubble assistant thinking" aria-label={s.loading}>
                      <span className="dots">
                        <span />
                        <span />
                        <span />
                      </span>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
          {footerThinking && (
            <div className="bubble assistant thinking">
              <span className="dots" aria-label={s.loading}>
                <span />
                <span />
                <span />
              </span>
            </div>
          )}
          <div ref={endRef} className="messages-end" aria-hidden />
        </div>

        {notice && <div className="banner ok">{notice}</div>}
        {error && <div className="banner error">{error}</div>}

        <div className="composer">
          <textarea
            rows={2}
            placeholder={s.agentPlaceholder}
            value={input}
            disabled={busy}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void onSend();
              }
            }}
          />
          <button type="button" className="btn primary" onClick={() => void onSend()} disabled={busy || !input.trim()}>
            {s.send}
          </button>
        </div>
      </div>
    </section>
  );
}
