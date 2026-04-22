import { useEffect, useRef } from "react";
import { MarkdownMessage } from "./MarkdownMessage";

export type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  requestId?: string;
};

type Props = {
  className?: string;
  messages: ChatMsg[];
  input: string;
  setInput: (v: string) => void;
  busy: boolean;
  error: string | null;
  suggestions: string[];
  onSend: () => void;
};

export function ChatPanel({
  className,
  messages,
  input,
  setInput,
  busy,
  error,
  suggestions,
  onSend,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, busy]);

  return (
    <section className={`chat-panel ${className ?? ""}`} aria-label="Agent chat">
      <div className="chat-panel-inner">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">
              <p>
                Ask anything. Replies can include <strong>Markdown tables</strong>,{" "}
                <strong>Mermaid</strong> diagrams (fenced <code className="inline-code">mermaid</code>
                ), <strong>Vega-Lite</strong> charts (fenced <code className="inline-code">vega-lite</code>{" "}
                JSON), and images (
                <code className="inline-code">https://</code>, <code className="inline-code">data:image/…</code>
                , or saved files under <code className="inline-code">/project/reports/…</code> served by the API).
              </p>
              <div className="suggestions">
                {suggestions.map((s) => (
                  <button key={s} type="button" className="chip" onClick={() => setInput(s)} disabled={busy}>
                    {s}
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
              <span className="dots" aria-label="Loading">
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
            placeholder="Message…"
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
            Send
          </button>
        </div>
      </div>
    </section>
  );
}
