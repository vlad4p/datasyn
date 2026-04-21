/**
 * API routing:
 * - Default: same-origin `/api` — Vite `server` and `preview` proxy to the brain (see `vite.config.ts`).
 *   That avoids CORS when you open the UI as `http://192.168.x.x:5173` / `vite preview --host`, etc.
 * - Set `VITE_API_BASE` only when the UI is served without that proxy (e.g. static files + remote API).
 * - Browser cannot use Docker DNS (`brain`); use published host ports or `/api` through Vite.
 */
export function getApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE;
  if (raw && String(raw).trim()) {
    return String(raw).replace(/\/$/, "");
  }
  return "";
}

/** Label for the dashboard (human-readable). */
export function getApiDisplayLabel(): string {
  const raw = import.meta.env.VITE_API_BASE;
  if (raw && String(raw).trim()) {
    return String(raw).replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    return `${window.location.origin}/api`;
  }
  return "/api";
}

function apiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBase();
  if (base) return `${base}${p}`;
  return `/api${p}`;
}

/** Resolved URL for brain `GET /artifacts/file` (honours `VITE_API_BASE` or same-origin `/api`). */
export function artifactFileUrl(relativeProjectPath: string): string {
  const clean = relativeProjectPath.replace(/^\/+/, "");
  return apiUrl(`/artifacts/file?path=${encodeURIComponent(clean)}`);
}

export async function postChat(message: string): Promise<string> {
  const res = await fetch(apiUrl("/agent/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err: unknown = await res.json().catch(() => ({}));
    const detail =
      typeof err === "object" && err !== null && "detail" in err
        ? String((err as { detail: unknown }).detail)
        : res.statusText;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { reply: string };
  return data.reply;
}

async function readFetchError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    if (j && typeof j.detail === "string") return j.detail;
  } catch {
    /* ignore */
  }
  return text || `${res.status} ${res.statusText}`;
}

/** ``GET /health`` — includes LLM snapshot when served by a current brain. */
export type BrainHealth = {
  status: string;
  litellm_base?: string | null;
  has_key?: boolean;
  in_docker?: boolean;
  chat_model?: string;
};

export type LlmConfig = {
  litellm_base: string | null;
  has_key: boolean;
  in_docker: boolean;
  chat_model: string;
};

export async function getHealth(): Promise<BrainHealth> {
  const res = await fetch(apiUrl("/health"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<BrainHealth>;
}

/** Derive LLM block from expanded ``GET /health`` (new brains). */
export function llmConfigFromHealth(h: BrainHealth): LlmConfig | null {
  if (h.litellm_base === undefined && h.chat_model === undefined) {
    return null;
  }
  return {
    litellm_base: h.litellm_base ?? null,
    has_key: Boolean(h.has_key),
    in_docker: Boolean(h.in_docker),
    chat_model: String(h.chat_model ?? ""),
  };
}

/**
 * LLM config: prefers fields embedded in ``cachedHealth`` from ``GET /health`` to avoid a second
 * request; falls back to ``GET /health/llm/config`` for older API builds.
 */
export async function getLlmConfig(cachedHealth?: BrainHealth): Promise<LlmConfig> {
  const h = cachedHealth ?? (await getHealth());
  const fromHealth = llmConfigFromHealth(h);
  if (fromHealth) {
    return fromHealth;
  }
  const res = await fetch(apiUrl("/health/llm/config"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<LlmConfig>;
}

export async function probeLlm(): Promise<unknown> {
  const res = await fetch(apiUrl("/health/llm"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json();
}
