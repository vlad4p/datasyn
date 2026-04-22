/**
 * API routing (browser → brain):
 * - Dev default: `fetch('/api/...')` on the Vite origin (`:5173`). Vite proxies `/api` → brain
 *   (`vite.config.ts`: `VITE_PROXY_TARGET`, default `http://127.0.0.1:8002` = Docker `brain` host port).
 * - Set `VITE_API_BASE` only without Vite’s proxy; must target that same brain URL.
 * - The browser never sends `LITELLM_KEY`. Wrong proxy host/port → wrong process → stale key / LiteLLM 401.
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

/** Match Vite proxy `timeout` / `proxyTimeout` (long agent turns). */
const CHAT_FETCH_MS = 600_000;

export type ChatResponsePayload = {
  reply: string;
  request_id: string;
  debug?: Record<string, unknown> | null;
};

/** Latest chat correlation + optional server debug (DATACYBER_PIPELINE_DEBUG=1 on brain). */
export type PipelineTrace = {
  requestId: string;
  debug: ChatResponsePayload["debug"];
  at: number;
} | null;

export async function postChat(message: string): Promise<ChatResponsePayload> {
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), CHAT_FETCH_MS);
  const t0 = performance.now();
  try {
    const res = await fetch(apiUrl("/agent/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal: ctrl.signal,
    });
    if (import.meta.env.DEV) {
      console.info(
        "[datacyber] POST /agent/chat",
        res.status,
        res.headers.get("X-Request-ID"),
        `${Math.round(performance.now() - t0)}ms`,
      );
    }
    if (!res.ok) {
      const err: unknown = await res.json().catch(() => ({}));
      const detail =
        typeof err === "object" && err !== null && "detail" in err
          ? String((err as { detail: unknown }).detail)
          : res.statusText;
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const data = (await res.json()) as ChatResponsePayload;
    return data;
  } catch (e) {
      if (e instanceof Error && e.name === "AbortError") {
        throw new Error(
          `Chat request timed out after ${CHAT_FETCH_MS / 1000}s (increase CHAT_FETCH_MS in ui/src/api.ts or check brain/LiteLLM).`,
        );
      }
      throw e;
    } finally {
      window.clearTimeout(t);
    }
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

/** ``GET /health`` — includes LLM snapshot and optional ``pipeline`` (architecture / MCP URLs). */
export type BrainHealth = {
  status: string;
  litellm_base?: string | null;
  has_key?: boolean;
  /** Last 4 chars of `LITELLM_KEY` loaded by the brain (compare to LiteLLM 401 messages like `...RbPw`). */
  litellm_key_suffix?: string | null;
  /** If set, LangChain may read `OPENAI_API_KEY` for other code paths; ChatOpenAI uses `LITELLM_KEY` explicitly. */
  openai_api_key_env_set?: boolean;
  openai_api_key_env_suffix?: string | null;
  in_docker?: boolean;
  chat_model?: string;
  /** Same object as ``GET /health/pipeline``; embedded so the UI needs only one request. */
  pipeline?: Record<string, unknown>;
};

export type LlmConfig = {
  litellm_base: string | null;
  has_key: boolean;
  litellm_key_suffix: string | null;
  openai_api_key_env_set: boolean;
  openai_api_key_env_suffix: string | null;
  in_docker: boolean;
  chat_model: string;
};

/** True when `GET /health` is only `{ "status": "ok" }` — often Vite proxied to the wrong port/process, not the Docker brain. */
export function isStubHealthResponse(h: BrainHealth): boolean {
  return (
    h.status === "ok" &&
    h.litellm_base === undefined &&
    h.pipeline === undefined &&
    h.has_key === undefined &&
    h.chat_model === undefined
  );
}

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
    litellm_key_suffix:
      typeof h.litellm_key_suffix === "string" ? h.litellm_key_suffix : null,
    openai_api_key_env_set: Boolean(h.openai_api_key_env_set),
    openai_api_key_env_suffix:
      typeof h.openai_api_key_env_suffix === "string" ? h.openai_api_key_env_suffix : null,
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
  const raw = (await res.json()) as Record<string, unknown>;
  return {
    litellm_base: (raw.litellm_base as string | null) ?? null,
    has_key: Boolean(raw.has_key),
    litellm_key_suffix:
      typeof raw.litellm_key_suffix === "string" ? raw.litellm_key_suffix : null,
    openai_api_key_env_set: Boolean(raw.openai_api_key_env_set),
    openai_api_key_env_suffix:
      typeof raw.openai_api_key_env_suffix === "string" ? raw.openai_api_key_env_suffix : null,
    in_docker: Boolean(raw.in_docker),
    chat_model: String(raw.chat_model ?? ""),
  };
}

export async function probeLlm(): Promise<unknown> {
  const res = await fetch(apiUrl("/health/llm"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json();
}

/**
 * Optional alias: same JSON as ``GET /health`` → ``pipeline`` (older brains may 404 — prefer ``pipeline`` on health).
 */
export async function getHealthPipeline(): Promise<Record<string, unknown> | null> {
  const res = await fetch(apiUrl("/health/pipeline"));
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<Record<string, unknown>>;
}

/** Summary row from ``GET /catalog/datasets`` (brain invokes MCP ``catalog_list_datasets``). */
export type CatalogDatasetSummary = {
  id?: string | null;
  fullyQualifiedName?: string | null;
  name?: string | null;
  displayName?: string | null;
  description?: string | null;
  tableType?: string | null;
  service?: { name?: string; type?: string };
  database?: { name?: string };
  schema?: { name?: string };
  columnCount?: number;
  tagCount?: number;
  updatedAt?: string;
  createdAt?: string;
};

export type CatalogDatasetsResponse = {
  ok?: boolean;
  count?: number;
  datasets?: CatalogDatasetSummary[];
};

export async function getCatalogDatasets(params?: {
  limit?: number;
  service_name?: string;
  database_name?: string;
  schema_name?: string;
}): Promise<CatalogDatasetSummary[]> {
  const q = new URLSearchParams();
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.service_name) q.set("service_name", params.service_name);
  if (params?.database_name) q.set("database_name", params.database_name);
  if (params?.schema_name) q.set("schema_name", params.schema_name);
  const qs = q.toString();
  const path = qs ? `/catalog/datasets?${qs}` : "/catalog/datasets";
  const res = await fetch(apiUrl(path));
  if (!res.ok) throw new Error(await readFetchError(res));
  const data = (await res.json()) as CatalogDatasetsResponse;
  return Array.isArray(data.datasets) ? data.datasets : [];
}
