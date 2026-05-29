/**
 * Persist multi-session chat history in the browser (scoped by user id when logged in).
 */
import type { ChatMsg } from "./types/chat";

const LEGACY_KEY = "datasyn-chat-session-v1";
const ACTIVE_KEY = "datasyn-chat-active-v1";
const INDEX_KEY = "datasyn-chat-history-index-v1";
const SESSION_PREFIX = "datasyn-chat-session-v1-";

type StoredMsg = Pick<
  ChatMsg,
  "id" | "role" | "content" | "subagentContent" | "requestId"
>;

export type ChatSessionSummary = {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  preview: string;
  userId: string | null;
};

type SessionIndex = ChatSessionSummary[];

function sessionKey(id: string): string {
  return `${SESSION_PREFIX}${id}`;
}

function newSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function isStoredMsg(x: unknown): x is StoredMsg {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    (o.role === "user" || o.role === "assistant") &&
    typeof o.content === "string"
  );
}

function readIndex(): SessionIndex {
  try {
    const raw = localStorage.getItem(INDEX_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (row): row is ChatSessionSummary =>
        !!row &&
        typeof row === "object" &&
        typeof (row as ChatSessionSummary).id === "string" &&
        typeof (row as ChatSessionSummary).title === "string" &&
        typeof (row as ChatSessionSummary).updatedAt === "string",
    );
  } catch {
    return [];
  }
}

function writeIndex(index: SessionIndex): void {
  localStorage.setItem(INDEX_KEY, JSON.stringify(index));
}

function deriveTitle(messages: ChatMsg[]): string {
  const first = messages.find((m) => m.role === "user" && m.content.trim());
  if (!first) return "";
  const text = first.content.trim().replace(/\s+/g, " ");
  return text.length > 56 ? `${text.slice(0, 53)}…` : text;
}

function derivePreview(messages: ChatMsg[]): string {
  const ready = messages.filter((m) => !(m.role === "assistant" && m.streaming));
  const last = [...ready].reverse().find((m) => m.content.trim());
  if (!last) return "";
  const text = last.content.trim().replace(/\s+/g, " ");
  return text.length > 140 ? `${text.slice(0, 137)}…` : text;
}

function toStored(messages: ChatMsg[]): StoredMsg[] {
  return messages
    .filter((m) => !(m.role === "assistant" && m.streaming))
    .map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      subagentContent: m.subagentContent,
      requestId: m.requestId,
    }));
}

function fromStored(rows: StoredMsg[]): ChatMsg[] {
  return rows.map((row) => ({
    id: row.id,
    role: row.role,
    content: row.content,
    subagentContent: row.subagentContent,
    requestId: row.requestId,
    streaming: false,
    activity: null,
  }));
}

function migrateLegacySession(): void {
  try {
    const raw = localStorage.getItem(LEGACY_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) || parsed.length === 0) {
      localStorage.removeItem(LEGACY_KEY);
      return;
    }
    const rows: StoredMsg[] = [];
    for (const row of parsed) {
      if (isStoredMsg(row)) rows.push(row);
    }
    if (rows.length === 0) {
      localStorage.removeItem(LEGACY_KEY);
      return;
    }
    const messages = fromStored(rows);
    const id = newSessionId();
    localStorage.setItem(sessionKey(id), JSON.stringify(rows));
    const now = new Date().toISOString();
    const index = readIndex();
    index.unshift({
      id,
      title: deriveTitle(messages) || "Chat",
      updatedAt: now,
      messageCount: messages.length,
      preview: derivePreview(messages),
      userId: null,
    });
    writeIndex(index);
    localStorage.setItem(ACTIVE_KEY, id);
    localStorage.removeItem(LEGACY_KEY);
  } catch {
    localStorage.removeItem(LEGACY_KEY);
  }
}

let migrated = false;

function ensureMigrated(): void {
  if (migrated) return;
  migrated = true;
  migrateLegacySession();
}

export function getActiveSessionId(): string {
  ensureMigrated();
  try {
    const existing = localStorage.getItem(ACTIVE_KEY);
    if (existing) return existing;
  } catch {
    /* private mode */
  }
  const id = newSessionId();
  setActiveSessionId(id);
  return id;
}

export function setActiveSessionId(id: string): void {
  try {
    localStorage.setItem(ACTIVE_KEY, id);
  } catch {
    /* quota or private mode */
  }
}

export function createChatSession(userId: string | null): string {
  const id = newSessionId();
  const now = new Date().toISOString();
  const index = readIndex();
  index.unshift({
    id,
    title: "",
    updatedAt: now,
    messageCount: 0,
    preview: "",
    userId,
  });
  writeIndex(index);
  try {
    localStorage.setItem(sessionKey(id), JSON.stringify([]));
  } catch {
    /* quota or private mode */
  }
  setActiveSessionId(id);
  return id;
}

export function loadChatSession(sessionId?: string): ChatMsg[] {
  ensureMigrated();
  const id = sessionId ?? getActiveSessionId();
  try {
    const raw = localStorage.getItem(sessionKey(id));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const rows: StoredMsg[] = [];
    for (const row of parsed) {
      if (isStoredMsg(row)) rows.push(row);
    }
    return fromStored(rows);
  } catch {
    return [];
  }
}

export function saveChatSession(
  messages: ChatMsg[],
  userId: string | null,
  sessionId?: string,
): void {
  ensureMigrated();
  const id = sessionId ?? getActiveSessionId();
  const payload = toStored(messages);
  const title = deriveTitle(messages);
  const preview = derivePreview(messages);
  const now = new Date().toISOString();

  try {
    localStorage.setItem(sessionKey(id), JSON.stringify(payload));
  } catch {
    return;
  }

  const index = readIndex();
  const existing = index.find((row) => row.id === id);
  if (existing) {
    existing.updatedAt = now;
    existing.messageCount = payload.length;
    existing.preview = preview;
    existing.userId = userId;
    if (title) existing.title = title;
  } else {
    index.unshift({
      id,
      title: title || "Chat",
      updatedAt: now,
      messageCount: payload.length,
      preview,
      userId,
    });
  }
  index.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  writeIndex(index);
}

export function listChatSessions(userId: string | null): ChatSessionSummary[] {
  ensureMigrated();
  const scope = userId ?? null;
  return readIndex()
    .filter((row) => row.userId === scope && row.messageCount > 0)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}
