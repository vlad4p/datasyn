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
  requestId?: string;
};

type Props = {
  className?: string;
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
  locale,
  messages,
  input,
  setInput,
  busy,
  error,
  onSend,
}: Props) {
  const s = uiStrings(locale);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, busy]);

  return (
    <section className={`chat-panel ${className ?? ""}`} aria-label={s.chatAria}>
      <div className="chat-panel-inner">
        <div className="messages">
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
          {messages.map((m) => (
            <MarkdownMessage key={m.id} role={m.role} content={m.content} />
          ))}
          {busy && (
            <div className="bubble assistant thinking">
              <span className="dots" aria-label={s.loading}>
                <span />
                <span />
                <span />
              </span>
            </div>
          )}
          <div ref={endRef} />
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
