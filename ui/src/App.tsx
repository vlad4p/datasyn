import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { ChatResponsePayload } from "./api";
import { exportAnalysis, postChatStream } from "./api";
import type { ChatHistoryTurn, ChatStreamEvent } from "./api";
import { AgentChatPanel, type ChatMsg } from "./components/AgentChatPanel";
import { AnalysisGallery } from "./components/AnalysisGallery";
import { AppHeader } from "./components/AppHeader";
import { DatasetCatalog } from "./components/DatasetCatalog";
import { loadChatSession, saveChatSession } from "./chatSessionStorage";
import { readStoredLocale, persistLocale, uiStrings, type UiLocale } from "./locale";
import { newId } from "./newId";
import { formatStreamStep, formatStreamToolDelta } from "./streamActivityFormat";

const AGENT_PANEL_ID = "agent-workspace";
const DATASETS_PANEL_ID = "datasets-panel";
const ANALYSES_PANEL_ID = "analyses-panel";

type WorkspaceTab = "agent" | "datasets" | "analyses";

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
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [analysisRefresh, setAnalysisRefresh] = useState(0);
  const [pendingDatasetFqn, setPendingDatasetFqn] = useState<string | null>(null);
  const narrow = useNarrowLayout();
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("agent");
  const s = uiStrings(locale);

  const onLocaleChange = useCallback((l: UiLocale) => {
    persistLocale(l);
    setLocale(l);
  }, []);

  const focusPanel = useCallback((id: string) => {
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }, []);

  const selectTab = useCallback(
    (tab: WorkspaceTab, panelId: string) => {
      setWorkspaceTab(tab);
      if (!narrow) focusPanel(panelId);
    },
    [narrow, focusPanel],
  );

  const handleNewChat = useCallback(() => {
    if (busy) return;
    setMessages([]);
    setError(null);
    setInput("");
    saveChatSession([]);
    setWorkspaceTab("agent");
    if (!narrow) focusPanel(AGENT_PANEL_ID);
  }, [busy, narrow, focusPanel]);

  useEffect(() => {
    if (busy) return;
    saveChatSession(messages);
  }, [messages, busy]);

  const handleAnalyzeDataset = useCallback(
    (fqn: string) => {
      setPendingDatasetFqn(fqn);
      const prompt =
        locale === "es"
          ? `Analiza el dataset \`${fqn}\`: resume columnas, calidad y 3 preguntas de negocio.`
          : `Analyze dataset \`${fqn}\`: summarize columns, quality, and 3 business questions.`;
      setInput(prompt);
      selectTab("agent", AGENT_PANEL_ID);
    },
    [locale, selectTab],
  );

  const handleExportAnalysis = useCallback(async () => {
    const ready = messages.filter((m) => !(m.role === "assistant" && m.streaming));
    const exportMsgs = ready
      .filter((m) => (m.content || "").trim())
      .map((m) => ({ role: m.role, content: m.content }));
    if (exportMsgs.length === 0) return;
    setExporting(true);
    setError(null);
    try {
      const requestIds = ready
        .map((m) => m.requestId)
        .filter((id): id is string => Boolean(id));
      await exportAnalysis({
        messages: exportMsgs,
        locale,
        dataset_fqn: pendingDatasetFqn,
        request_ids: requestIds,
      });
      setAnalysisRefresh((n) => n + 1);
      setError(null);
      setExportNotice(s.exportSuccess);
      window.setTimeout(() => setExportNotice(null), 4000);
    } catch (e) {
      setError(`${s.exportFailed}: ${String(e)}`);
    } finally {
      setExporting(false);
    }
  }, [locale, messages, pendingDatasetFqn, s.exportFailed, s.exportSuccess]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    const history: ChatHistoryTurn[] = messages.map((m) => ({
      role: m.role === "user" ? "user" : "assistant",
      content: m.content,
    }));
    setInput("");
    setError(null);
    const userMsg: Msg = { id: newId(), role: "user", content: text };
    const assistantId = newId();
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
      setMessages((m) => m.map((msg) => (msg.id === assistantId ? fn(msg as Msg) : msg)));
    };
    try {
      await postChatStream(text, {
        locale,
        history,
        onEvent: (ev: ChatStreamEvent) => {
          if (ev.event === "start") {
            patchAssistant((row) => ({ ...row, requestId: ev.request_id }));
            return;
          }
          if (ev.event === "token") {
            const t = ev.text ?? "";
            if (!t) return;
            patchAssistant((row) => {
              if (row.role !== "assistant") return row;
              if (ev.source === "subagent") {
                return { ...row, subagentContent: (row.subagentContent ?? "") + t };
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
              activity: formatStreamToolDelta(ev.tool_name, ev.args_fragment, ev.source, locale),
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
              content: row.content.trim() ? row.content : `Error: ${ev.message}`,
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
                content: msg.content.trim() ? msg.content : `Error: ${String(e)}`,
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
    (narrow && workspaceTab === "agent" ? " layout-panels--mobile-chat" : "") +
    (narrow && workspaceTab === "datasets" ? " layout-panels--mobile-dash" : "") +
    (narrow && workspaceTab === "analyses" ? " layout-panels--mobile-analyses" : "");

  return (
    <div className="app-shell">
      <AppHeader locale={locale} onLocaleChange={onLocaleChange} />

      <div className="layout-main">
        <nav className="workspace-nav" aria-label={s.workspaceNavAria}>
          <div className="workspace-nav__tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={workspaceTab === "agent"}
              className={`workspace-nav__tab${workspaceTab === "agent" ? " is-active" : ""}`}
              onClick={() => selectTab("agent", AGENT_PANEL_ID)}
            >
              {s.navAgent}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={workspaceTab === "datasets"}
              className={`workspace-nav__tab${workspaceTab === "datasets" ? " is-active" : ""}`}
              onClick={() => selectTab("datasets", DATASETS_PANEL_ID)}
            >
              {s.navDatasets}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={workspaceTab === "analyses"}
              className={`workspace-nav__tab${workspaceTab === "analyses" ? " is-active" : ""}`}
              onClick={() => selectTab("analyses", ANALYSES_PANEL_ID)}
            >
              {s.navAnalyses}
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
          <AgentChatPanel
            id={AGENT_PANEL_ID}
            className={workspaceTab === "agent" ? "panel-chat" : "panel-chat panel-hidden"}
            locale={locale}
            messages={messages}
            input={input}
            setInput={setInput}
            busy={busy}
            error={error}
            notice={exportNotice}
            onSend={send}
            onExportAnalysis={() => void handleExportAnalysis()}
            exporting={exporting}
          />

          <DatasetCatalog
            id={DATASETS_PANEL_ID}
            className={workspaceTab === "datasets" ? "panel-dash" : "panel-dash panel-hidden"}
            locale={locale}
            onAnalyzeDataset={handleAnalyzeDataset}
          />

          <AnalysisGallery
            id={ANALYSES_PANEL_ID}
            className={workspaceTab === "analyses" ? "panel-analyses" : "panel-analyses panel-hidden"}
            locale={locale}
            refreshToken={analysisRefresh}
          />
        </div>
      </div>
    </div>
  );
}
