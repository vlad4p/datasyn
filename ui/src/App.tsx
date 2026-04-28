import { useCallback, useState } from "react";
import { postChat } from "./api";
import type { ChatResponsePayload } from "./api";
import { AppHeader } from "./components/AppHeader";
import { ChatPanel, type ChatMsg } from "./components/ChatPanel";
import { Dashboard } from "./components/Dashboard";
import { readStoredLocale, persistLocale, type UiLocale } from "./locale";

type Msg = ChatMsg & {
  pipelineDebug?: ChatResponsePayload["debug"];
};

export default function App() {
  const [locale, setLocale] = useState<UiLocale>(() => readStoredLocale());
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onLocaleChange = useCallback((l: UiLocale) => {
    persistLocale(l);
    setLocale(l);
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError(null);
    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content: text };
    setMessages((m) => [...m, userMsg]);
    setBusy(true);
    try {
      const out = await postChat(text, { locale });
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
  }, [input, busy, locale]);

  return (
    <div className="app-shell">
      <AppHeader locale={locale} onLocaleChange={onLocaleChange} />

      <div className="layout-main">
        <ChatPanel
          className="panel-chat"
          locale={locale}
          messages={messages}
          input={input}
          setInput={setInput}
          busy={busy}
          error={error}
          onSend={send}
        />

        <Dashboard className="panel-dash" locale={locale} />
      </div>
    </div>
  );
}
