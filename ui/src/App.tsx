import { useCallback, useEffect, useRef, useState } from "react";
import { postChat } from "./api";
import type { ChatResponsePayload, PipelineTrace } from "./api";
import { Dashboard } from "./components/Dashboard";
import { MarkdownMessage } from "./components/MarkdownMessage";

type Msg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  requestId?: string;
  pipelineDebug?: ChatResponsePayload["debug"];
};

const SUGGESTIONS = [
  "List all files under /data-local (including subfolders) using duckdb tools.",
  "What models does the brain use? Summarize litellm_base and CHAT_MODEL from your tools.",
  "Run SELECT * FROM example_sales LIMIT 10 and format results as a markdown table.",
  "Reply with a Mermaid flowchart in a ```mermaid fenced block showing ingest → warehouse → report.",
];

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pipelineTrace, setPipelineTrace] = useState<PipelineTrace>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const scrollToEnd = () => endRef.current?.scrollIntoView({ behavior: "smooth" });

  useEffect(() => {
    scrollToEnd();
  }, [messages.length, busy]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content: text };
    setMessages((m) => [...m, userMsg]);
    setBusy(true);
    try {
      const out = await postChat(text);
      setPipelineTrace({
        requestId: out.request_id,
        debug: out.debug ?? null,
        at: Date.now(),
      });
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: out.reply,
          requestId: out.request_id,
          pipelineDebug: out.debug ?? undefined,
        },
      ]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }, [input, busy]);

  return (
    <div className="app-shell">
      <header className="top-bar">
        <div className="brand">
          <span className="logo" aria-hidden />
          <div>
            <h1>Datacyber</h1>
            <p className="tagline">Agent chat · warehouse · catalog</p>
          </div>
        </div>
      </header>

      <div className="layout">
        <main className="chat-main">
          <div className="messages">
            {messages.length === 0 && (
              <div className="empty">
                <p>
                  Ask anything. Replies can include <strong>Markdown tables</strong>,{" "}
                  <strong>Mermaid</strong> diagrams (fenced code with language <code className="inline-code">mermaid</code>
                  ), <strong>Vega-Lite</strong> charts (fenced <code className="inline-code">vega-lite</code> JSON), and
                  images (<code className="inline-code">https://</code>, <code className="inline-code">data:image/…</code>
                  , or saved files under <code className="inline-code">/project/reports/…</code> served by the API).
                </p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
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
                  void send();
                }
              }}
            />
            <button type="button" className="btn primary" onClick={() => void send()} disabled={busy || !input.trim()}>
              Send
            </button>
          </div>
        </main>

        <Dashboard pipelineTrace={pipelineTrace} />
      </div>
    </div>
  );
}
