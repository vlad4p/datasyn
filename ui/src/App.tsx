import { useCallback, useState } from "react";
import { postChat } from "./api";
import type { ChatResponsePayload, PipelineTrace } from "./api";
import { AppHeader } from "./components/AppHeader";
import { CatalogPanel } from "./components/CatalogPanel";
import { ChatPanel, type ChatMsg } from "./components/ChatPanel";
import { Dashboard } from "./components/Dashboard";

type Msg = ChatMsg & {
  pipelineDebug?: ChatResponsePayload["debug"];
};

const SUGGESTIONS = [
  "List all files under /data-local (including subfolders) using duckdb tools.",
  "What models does the brain use? Summarize litellm_base and CHAT_MODEL from your tools.",
  "Use catalog_list_datasets and summarize FQN, schema, and column counts.",
  "Run SELECT * FROM example_sales LIMIT 10 and format results as a markdown table.",
  "Reply with a Mermaid flowchart in a ```mermaid fenced block showing ingest → warehouse → report.",
];

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pipelineTrace, setPipelineTrace] = useState<PipelineTrace>(null);

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
      <AppHeader />

      <div className="layout-main">
        <CatalogPanel className="panel-catalog" />

        <ChatPanel
          className="panel-chat"
          messages={messages}
          input={input}
          setInput={setInput}
          busy={busy}
          error={error}
          suggestions={SUGGESTIONS}
          onSend={send}
        />

        <Dashboard className="panel-dash" pipelineTrace={pipelineTrace} />
      </div>
    </div>
  );
}
