import { useCallback, useEffect, useMemo, useState } from "react";
import { listChatSessions, type ChatSessionSummary } from "../chatHistoryStorage";
import type { UiLocale } from "../locale";
import { uiStrings } from "../locale";

export type WorkspaceView = "agent" | "datasets" | "tools" | "analyses" | "settings";

type Props = {
  locale: UiLocale;
  active: WorkspaceView;
  collapsed: boolean;
  busy: boolean;
  chatHistoryRefresh?: number;
  activeChatSessionId?: string | null;
  userId?: string | null;
  onSelect: (view: WorkspaceView) => void;
  onNewChat: () => void;
  onOpenChat?: (sessionId: string) => void;
  onToggleCollapse: () => void;
};

function NavIcon({ kind }: { kind: "chat" | "datasets" | "tools" | "analysis" | "settings" | "new" }) {
  return (
    <span className="sidebar-nav__icon" aria-hidden>
      {kind === "chat" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        </svg>
      )}
      {kind === "datasets" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M3 5v6c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
          <path d="M3 11v6c0 1.66 4.03 3 9 3s9-1.34 9-3v-6" />
        </svg>
      )}
      {kind === "tools" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
        </svg>
      )}
      {kind === "analysis" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
          <path d="M3 3v18h18" />
          <path d="M7 16l4-6 4 3 5-8" />
        </svg>
      )}
      {kind === "settings" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
        </svg>
      )}
      {kind === "new" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
          <path d="M12 5v14M5 12h14" />
        </svg>
      )}
    </span>
  );
}

function formatChatDate(iso: string, locale: UiLocale): string {
  try {
    return new Date(iso).toLocaleString(locale === "es" ? "es" : "en", {
      dateStyle: "short",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export function WorkspaceSidebar({
  locale,
  active,
  collapsed,
  busy,
  chatHistoryRefresh = 0,
  activeChatSessionId = null,
  userId = null,
  onSelect,
  onNewChat,
  onOpenChat,
  onToggleCollapse,
}: Props) {
  const s = uiStrings(locale);
  const a = s.analyses;
  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([]);

  const refreshChats = useCallback(() => {
    setChatSessions(listChatSessions(userId ?? null));
  }, [userId]);

  useEffect(() => {
    refreshChats();
  }, [refreshChats, chatHistoryRefresh, userId]);

  const defaultChatTitle = useMemo(
    () => (locale === "es" ? "Chat sin título" : "Untitled chat"),
    [locale],
  );

  const items: { id: WorkspaceView; label: string; icon: "chat" | "datasets" | "tools" | "analysis" | "settings" }[] = [
    { id: "agent", label: s.navAgent, icon: "chat" },
    { id: "datasets", label: s.navDatasets, icon: "datasets" },
    { id: "tools", label: s.navSkillsTools, icon: "tools" },
    { id: "analyses", label: s.navAnalyses, icon: "analysis" },
    { id: "settings", label: s.navAgentConfig, icon: "settings" },
  ];

  return (
    <aside
      className={`workspace-sidebar${collapsed ? " workspace-sidebar--collapsed" : ""}`}
      aria-label={s.workspaceNavAria}
    >
      <nav className="sidebar-nav">
        <button
          type="button"
          className="sidebar-nav__item sidebar-nav__item--action"
          onClick={onNewChat}
          disabled={busy}
          title={busy ? s.loading : s.newChat}
        >
          <NavIcon kind="new" />
          {!collapsed && <span className="sidebar-nav__label">{s.newChat}</span>}
        </button>

        <div className="sidebar-nav__divider" role="presentation" />

        <ul className="sidebar-nav__list" role="list">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={`sidebar-nav__item${active === item.id ? " is-active" : ""}`}
                aria-current={active === item.id ? "page" : undefined}
                onClick={() => onSelect(item.id)}
                title={collapsed ? item.label : undefined}
              >
                <NavIcon kind={item.icon} />
                {!collapsed && <span className="sidebar-nav__label">{item.label}</span>}
              </button>
            </li>
          ))}
        </ul>

        {!collapsed && (
          <section className="sidebar-chats" aria-labelledby="sidebar-chats-heading">
            <h2 className="sidebar-chats__heading" id="sidebar-chats-heading">
              {a.chatsTitle}
            </h2>
            {chatSessions.length === 0 ? (
              <p className="sidebar-chats__empty">{a.chatsEmpty}</p>
            ) : (
              <ul className="sidebar-chats__list" role="list">
                {chatSessions.map((session) => {
                  const title = session.title.trim() || defaultChatTitle;
                  const isActive =
                    active === "agent" && session.id === activeChatSessionId;
                  return (
                    <li key={session.id}>
                      <button
                        type="button"
                        className={`sidebar-chats__item${isActive ? " is-active" : ""}`}
                        onClick={() => onOpenChat?.(session.id)}
                        disabled={busy}
                        title={title}
                      >
                        <span className="sidebar-chats__title">{title}</span>
                        <span className="sidebar-chats__meta">
                          {formatChatDate(session.updatedAt, locale)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        )}
      </nav>

      <div className="sidebar-footer">
        <button
          type="button"
          className="sidebar-footer__collapse btn ghost"
          onClick={onToggleCollapse}
          aria-expanded={!collapsed}
          title={collapsed ? s.sidebarExpand : s.sidebarCollapse}
        >
          <span className="sidebar-footer__chevron" aria-hidden>
            {collapsed ? "›" : "‹"}
          </span>
          {!collapsed && (
            <span className="sidebar-footer__collapse-label">{s.sidebarCollapse}</span>
          )}
        </button>
      </div>
    </aside>
  );
}
