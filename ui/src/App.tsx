import { useCallback, useEffect, useMemo, useState } from "react";
import type { ChatResponsePayload } from "./api";
import { exportAnalysis, postChatStream } from "./api";
import type { ChatHistoryTurn, ChatStreamEvent } from "./api";
import { useAuth } from "./auth/AuthContext";
import { AgentChatPanel, type ChatMsg } from "./components/AgentChatPanel";
import { AnalysisGallery } from "./components/AnalysisGallery";
import { AppHeader } from "./components/AppHeader";
import { DatasetCatalog } from "./components/DatasetCatalog";
import { LoginPage } from "./components/LoginPage";
import { SkillsToolsView } from "./components/SkillsToolsView";
import { WorkspaceSidebar, type WorkspaceView } from "./components/WorkspaceSidebar";
import {
  createChatSession,
  getActiveSessionId,
  loadChatSession,
  saveChatSession,
  setActiveSessionId,
} from "./chatHistoryStorage";
import { readStoredLocale, persistLocale, uiStrings, type UiLocale } from "./locale";
import { newId } from "./newId";
import { formatStreamStep, formatStreamToolDelta } from "./streamActivityFormat";
import { persistSidebarCollapsed, readSidebarCollapsed } from "./workspaceSidebarStorage";

const AGENT_PANEL_ID = "agent-workspace";
const DATASETS_PANEL_ID = "datasets-panel";
const TOOLS_PANEL_ID = "skills-tools-panel";
const ANALYSES_PANEL_ID = "analyses-panel";

type Msg = ChatMsg & {
  pipelineDebug?: ChatResponsePayload["debug"];
};

export default function App() {
  const auth = useAuth();
  const [locale, setLocale] = useState<UiLocale>(() => readStoredLocale());
  const s = uiStrings(locale);

  const authError = useMemo(() => {
    if (typeof window === "undefined") return null;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("auth_error");
    if (!code) return null;
    if (code === "profile_failed") return s.auth.profileFailed;
    return s.auth.oauthFailed;
  }, [s.auth.oauthFailed, s.auth.profileFailed]);

  useEffect(() => {
    if (!authError) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("auth_error");
    window.history.replaceState({}, "", url.pathname + url.search + url.hash);
  }, [authError]);

  const onLocaleChange = useCallback((l: UiLocale) => {
    persistLocale(l);
    setLocale(l);
  }, []);

  if (auth.loading) {
    return (
      <div className="login-shell">
        <main className="login-main">
          <p className="login-loading">{s.auth.loading}</p>
        </main>
      </div>
    );
  }

  if (auth.authEnabled && !auth.user) {
    return (
      <LoginPage
        locale={locale}
        onLocaleChange={onLocaleChange}
        providers={auth.providers}
        error={authError}
      />
    );
  }

  return (
    <AppWorkspace
      locale={locale}
      onLocaleChange={onLocaleChange}
      user={auth.user}
      onLogout={() => void auth.logout()}
    />
  );
}

type WorkspaceProps = {
  locale: UiLocale;
  onLocaleChange: (locale: UiLocale) => void;
  user: import("./api").AuthUser | null;
  onLogout: () => void;
};

function AppWorkspace({ locale, onLocaleChange, user, onLogout }: WorkspaceProps) {
  const [activeSessionId, setActiveSessionIdState] = useState(() => getActiveSessionId());
  const [messages, setMessages] = useState<Msg[]>(() => loadChatSession(getActiveSessionId()) as Msg[]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [analysisRefresh, setAnalysisRefresh] = useState(0);
  const [chatHistoryRefresh, setChatHistoryRefresh] = useState(0);
  const [pendingDatasetFqn, setPendingDatasetFqn] = useState<string | null>(null);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("agent");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => readSidebarCollapsed());
  const s = uiStrings(locale);
  const userId = user?.id ?? null;

  const selectView = useCallback((view: WorkspaceView) => {
    setWorkspaceView(view);
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      persistSidebarCollapsed(next);
      return next;
    });
  }, []);

  const handleNewChat = useCallback(() => {
    if (busy) return;
    const nextId = createChatSession(userId);
    setActiveSessionIdState(nextId);
    setMessages([]);
    setError(null);
    setInput("");
    setChatHistoryRefresh((n) => n + 1);
    setWorkspaceView("agent");
  }, [busy, userId]);

  const handleOpenChatSession = useCallback(
    (sessionId: string) => {
      if (busy) return;
      setActiveSessionId(sessionId);
      setActiveSessionIdState(sessionId);
      setMessages(loadChatSession(sessionId) as Msg[]);
      setError(null);
      setInput("");
      setWorkspaceView("agent");
    },
    [busy],
  );

  useEffect(() => {
    if (busy) return;
    saveChatSession(messages, userId, activeSessionId);
    setChatHistoryRefresh((n) => n + 1);
  }, [messages, busy, activeSessionId, userId]);

  const handleAnalyzeDataset = useCallback(
    (fqn: string) => {
      setPendingDatasetFqn(fqn);
      const prompt =
        locale === "es"
          ? `Analiza el dataset \`${fqn}\`: resume columnas, calidad y 3 preguntas de negocio.`
          : `Analyze dataset \`${fqn}\`: summarize columns, quality, and 3 business questions.`;
      setInput(prompt);
      setWorkspaceView("agent");
    },
    [locale],
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

  const layoutClass =
    "layout-workspace" +
    (sidebarCollapsed ? " layout-workspace--sidebar-collapsed" : "");

  return (
    <div className="app-shell">
      <AppHeader
        locale={locale}
        onLocaleChange={onLocaleChange}
        user={user}
        onLogout={onLogout}
      />

      <div className={layoutClass}>
        <WorkspaceSidebar
          locale={locale}
          active={workspaceView}
          collapsed={sidebarCollapsed}
          busy={busy}
          chatHistoryRefresh={chatHistoryRefresh}
          activeChatSessionId={activeSessionId}
          userId={userId}
          onSelect={selectView}
          onNewChat={handleNewChat}
          onOpenChat={handleOpenChatSession}
          onToggleCollapse={toggleSidebar}
        />

        <main className="workspace-main" id="workspace-main">
          {sidebarCollapsed && (
            <button
              type="button"
              className="workspace-main__expand-rail"
              onClick={toggleSidebar}
              aria-label={s.sidebarExpand}
              title={s.sidebarExpand}
            >
              <span aria-hidden>›</span>
            </button>
          )}

          <div className="workspace-main__content">
            <AgentChatPanel
              id={AGENT_PANEL_ID}
              className={workspaceView === "agent" ? "panel-chat" : "panel-chat panel-hidden"}
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
              className={workspaceView === "datasets" ? "panel-dash" : "panel-dash panel-hidden"}
              locale={locale}
              onAnalyzeDataset={handleAnalyzeDataset}
            />

            <SkillsToolsView
              id={TOOLS_PANEL_ID}
              className={workspaceView === "tools" ? "panel-tools" : "panel-tools panel-hidden"}
              locale={locale}
            />

            <AnalysisGallery
              id={ANALYSES_PANEL_ID}
              className={
                workspaceView === "analyses" ? "panel-analyses" : "panel-analyses panel-hidden"
              }
              locale={locale}
              refreshToken={analysisRefresh}
            />
          </div>
        </main>
      </div>
    </div>
  );
}
