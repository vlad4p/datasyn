import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";
import { MarkdownMessage } from "./MarkdownMessage";

export type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Text streamed from a ``task`` subagent (separate namespace). */
  subagentContent?: string;
  requestId?: string;
  /** True while SSE tokens are still arriving. */
  streaming?: boolean;
  /** Last graph step or tool name (brief status). */
  activity?: string | null;
};

type Props = {
  className?: string;
  id?: string;
  locale: UiLocale;
  messages: ChatMsg[];
  input: string;
  setInput: (v: string) => void;
  busy: boolean;
  error: string | null;
  onSend: () => void;
};

export function ChatPanel({
  className,
  id,
  locale,
  messages,
  input,
  setInput,
  busy,
  error,
  onSend,
}: Props) {
  const s = uiStrings(locale);
  /** Scrollable transcript region (growing “infinite” list). */
  const feedRef = useRef<HTMLDivElement>(null);
  /** Bottom sentinel: while visible (or near-visible), new tokens stick to bottom. */
  const endRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);

  const last = messages[messages.length - 1];
  const footerThinking =
    busy && !(last?.role === "assistant" && last?.streaming === true);

  /** Like infinite-scroll feeds: only auto-scroll while the user has not scrolled away from the bottom. */
  useEffect(() => {
    const root = feedRef.current;
    const target = endRef.current;
    if (!root || !target) return;

    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries[0]?.isIntersecting ?? true;
        stickToBottomRef.current = vis;
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

  return (
    <section id={id} className={`chat-panel ${className ?? ""}`} aria-label={s.chatAria}>
      <div className="chat-panel-inner">
        <div ref={feedRef} className="chat-transcript">
          {messages.length === 0 && (
            <div className="empty">
              <div className="empty-intro-md">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.chatEmpty}</ReactMarkdown>
              </div>
              <div className="suggestions">
                {s.suggestions.map((q) => (
                  <button key={q} type="button" className="chip" onClick={() => setInput(q)} disabled={busy}>
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

        {error && <div className="banner error">{error}</div>}

        <div className="composer">
          <textarea
            rows={2}
            placeholder={s.placeholder}
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
