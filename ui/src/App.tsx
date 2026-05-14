import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { ChatResponsePayload } from "./api";
import { postChatStream } from "./api";
import type { ChatHistoryTurn, ChatStreamEvent } from "./api";
import { AppHeader } from "./components/AppHeader";
import { ChatPanel, type ChatMsg } from "./components/ChatPanel";
import { Dashboard } from "./components/Dashboard";
import { loadChatSession, saveChatSession } from "./chatSessionStorage";
import { readStoredLocale, persistLocale, uiStrings, type UiLocale } from "./locale";
import { formatStreamStep, formatStreamToolDelta } from "./streamActivityFormat";

const CHAT_PANEL_ID = "chat-workspace";
const DASH_PANEL_ID = "dashboard-panel";

type WorkspaceTab = "chat" | "dashboard";

function useNarrowLayout(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia("(max-width: 900px)");
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia("(max-width: 900px)").matches,
    () => false,
  );
}

type Msg = ChatMsg & {
  pipelineDebug?: ChatResponsePayload["debug"];
};

export default function App() {
  const [locale, setLocale] = useState<UiLocale>(() => readStoredLocale());
  const [messages, setMessages] = useState<Msg[]>(() => loadChatSession() as Msg[]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const narrow = useNarrowLayout();
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("chat");
  const s = uiStrings(locale);
  const d = s.dashboard;

  const onLocaleChange = useCallback((l: UiLocale) => {
    persistLocale(l);
    setLocale(l);
  }, []);

  const focusPanel = useCallback((id: string) => {
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, []);

  const onSelectChatTab = useCallback(() => {
    setWorkspaceTab("chat");
    if (!narrow) focusPanel(CHAT_PANEL_ID);
  }, [narrow, focusPanel]);

  const onSelectDashboardTab = useCallback(() => {
    setWorkspaceTab("dashboard");
    if (!narrow) focusPanel(DASH_PANEL_ID);
  }, [narrow, focusPanel]);

  const handleNewChat = useCallback(() => {
    if (busy) return;
    setMessages([]);
    setError(null);
    setInput("");
    saveChatSession([]);
    setWorkspaceTab("chat");
    if (!narrow) focusPanel(CHAT_PANEL_ID);
  }, [busy, narrow, focusPanel]);

  useEffect(() => {
    if (busy) return;
    saveChatSession(messages);
  }, [messages, busy]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    const history: ChatHistoryTurn[] = messages.map((m) => ({
      role: m.role === "user" ? "user" : "assistant",
      content: m.content,
    }));
    if (import.meta.env.DEV) {
      console.info(
        "[datacyber] stream request history turns:",
        history.length,
        "(expected >0 after prior turns; 0 after fresh load until persistence fills)",
      );
    }
    setInput("");
    setError(null);
    const userMsg: Msg = { id: crypto.randomUUID(), role: "user", content: text };
    const assistantId = crypto.randomUUID();
    const assistantPlaceholder: Msg = {
      id: assistantId,
      role: "assistant",
      content: "",
      subagentContent: "",
      streaming: true,
      activity: null,
    };
    setMessages((m) => [...m, userMsg, assistantPlaceholder]);
    setBusy(true);
    let terminal = false;
    const patchAssistant = (fn: (row: Msg) => Msg) => {
      setMessages((m) =>
        m.map((msg) => (msg.id === assistantId ? fn(msg as Msg) : msg)),
      );
    };
    try {
      await postChatStream(text, {
        locale,
        history,
        onEvent: (ev: ChatStreamEvent) => {
          if (ev.event === "start") {
            patchAssistant((row) => ({
              ...row,
              requestId: ev.request_id,
            }));
            return;
          }
          if (ev.event === "token") {
            const t = ev.text ?? "";
            if (!t) return;
            patchAssistant((row) => {
              if (row.role !== "assistant") return row;
              if (ev.source === "subagent") {
                return {
                  ...row,
                  subagentContent: (row.subagentContent ?? "") + t,
                };
              }
              return { ...row, content: row.content + t };
            });
            return;
          }
          if (ev.event === "step") {
            patchAssistant((row) => ({
              ...row,
              activity: formatStreamStep(ev.node, ev.source, locale),
            }));
            return;
          }
          if (ev.event === "tool_delta") {
            patchAssistant((row) => ({
              ...row,
              activity: formatStreamToolDelta(
                ev.tool_name,
                ev.args_fragment,
                ev.source,
                locale,
              ),
            }));
            return;
          }
          if (ev.event === "done") {
            terminal = true;
            patchAssistant((row) => ({
              ...row,
              content: ev.reply,
              subagentContent: ev.subagent_reply,
              streaming: false,
              requestId: ev.request_id,
              pipelineDebug: ev.debug ?? undefined,
              activity: null,
            }));
            return;
          }
          if (ev.event === "error") {
            terminal = true;
            setError(ev.message);
            patchAssistant((row) => ({
              ...row,
              streaming: false,
              content: row.content.trim()
                ? row.content
                : `Error: ${ev.message}`,
              activity: null,
            }));
          }
        },
      });
      if (!terminal) {
        setError("Stream ended before completion.");
        patchAssistant((row) => ({ ...row, streaming: false, activity: null }));
      }
    } catch (e) {
      setError(String(e));
      setMessages((m) =>
        m.map((msg) =>
          msg.id === assistantId
            ? {
                ...msg,
                streaming: false,
                content: msg.content.trim()
                  ? msg.content
                  : `Error: ${String(e)}`,
                activity: null,
              }
            : msg,
        ),
      );
    } finally {
      setBusy(false);
    }
  }, [input, busy, locale, messages]);

  const panelsClass =
    "layout-panels" +
    (narrow && workspaceTab === "chat" ? " layout-panels--mobile-chat" : "") +
    (narrow && workspaceTab === "dashboard" ? " layout-panels--mobile-dash" : "");

  return (
    <div className="app-shell">
      <AppHeader locale={locale} onLocaleChange={onLocaleChange} />

      <div className="layout-main">
        <nav className="workspace-nav" aria-label={s.workspaceNavAria}>
          <div className="workspace-nav__tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={workspaceTab === "chat"}
              id="workspace-tab-chat"
              aria-controls={CHAT_PANEL_ID}
              className={`workspace-nav__tab${workspaceTab === "chat" ? " is-active" : ""}`}
              onClick={onSelectChatTab}
            >
              {s.navChat}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={workspaceTab === "dashboard"}
              id="workspace-tab-dashboard"
              aria-controls={DASH_PANEL_ID}
              className={`workspace-nav__tab${workspaceTab === "dashboard" ? " is-active" : ""}`}
              onClick={onSelectDashboardTab}
            >
              {d.title}
            </button>
          </div>
          <button
            type="button"
            className="btn ghost workspace-nav__new"
            onClick={handleNewChat}
            disabled={busy}
            title={busy ? s.loading : undefined}
          >
            {s.newChat}
          </button>
        </nav>

        <div className={panelsClass}>
          <ChatPanel
            id={CHAT_PANEL_ID}
            className="panel-chat"
            locale={locale}
            messages={messages}
            input={input}
            setInput={setInput}
            busy={busy}
            error={error}
            onSend={send}
          />

          <Dashboard id={DASH_PANEL_ID} className="panel-dash" locale={locale} />
        </div>
      </div>
    </div>
  );
}
