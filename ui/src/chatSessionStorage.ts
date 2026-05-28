/**
 * Persist conversation turns in the browser so POST /agent/chat/stream still sends
 * `history` after refresh (the brain is stateless per request).
 */
import type { ChatMsg } from "./types/chat";

const KEY = "datacyber-chat-session-v1";

type StoredMsg = Pick<
  ChatMsg,
  "id" | "role" | "content" | "subagentContent" | "requestId"
>;

function isStoredMsg(x: unknown): x is StoredMsg {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    (o.role === "user" || o.role === "assistant") &&
    typeof o.content === "string"
  );
}

export function loadChatSession(): ChatMsg[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const out: ChatMsg[] = [];
    for (const row of parsed) {
      if (!isStoredMsg(row)) continue;
      out.push({
        id: row.id,
        role: row.role,
        content: row.content,
        subagentContent: row.subagentContent,
        requestId: row.requestId,
        streaming: false,
        activity: null,
      });
    }
    return out;
  } catch {
    return [];
  }
}

export function saveChatSession(messages: ChatMsg[]): void {
  try {
    const ready = messages.filter(
      (m) => !(m.role === "assistant" && m.streaming),
    );
    const payload: StoredMsg[] = ready.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      subagentContent: m.subagentContent,
      requestId: m.requestId,
    }));
    localStorage.setItem(KEY, JSON.stringify(payload));
  } catch {
    /* quota or private mode */
  }
}
