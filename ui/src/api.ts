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

/** Brain HTTP URL for a path (respects `VITE_API_BASE` or same-origin `/api` proxy). */
export function brainApiUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBase();
  if (base) return `${base}${p}`;
  return `/api${p}`;
}

/** Resolved URL for brain `GET /artifacts/file` (honours `VITE_API_BASE` or same-origin `/api`). */
export function artifactFileUrl(relativeProjectPath: string): string {
  const clean = relativeProjectPath.replace(/^\/+/, "");
  return brainApiUrl(`/artifacts/file?path=${encodeURIComponent(clean)}`);
}

/** Match Vite proxy `timeout` / `proxyTimeout` (long agent turns). */
const CHAT_FETCH_MS = 600_000;

/** Include session cookies on brain API calls (OAuth login). */
export function brainFetch(input: string, init?: RequestInit): Promise<Response> {
  return fetch(input, { ...init, credentials: "include" });
}

export type AuthUser = {
  id: string;
  email?: string | null;
  name?: string | null;
  picture?: string | null;
  provider: string;
};

export type AuthMeResponse = {
  auth_enabled: boolean;
  authenticated: boolean;
  user: AuthUser | null;
  providers: string[];
};

export async function getAuthMe(): Promise<AuthMeResponse> {
  const res = await brainFetch(brainApiUrl("/auth/me"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<AuthMeResponse>;
}

export async function logoutAuth(): Promise<void> {
  const res = await brainFetch(brainApiUrl("/auth/logout"), { method: "POST" });
  if (!res.ok) throw new Error(await readFetchError(res));
}

export type ChatResponsePayload = {
  reply: string;
  request_id: string;
  debug?: Record<string, unknown> | null;
};

/** Latest chat correlation + optional server debug (DATASYN_PIPELINE_DEBUG=1 on brain). */
export type PipelineTrace = {
  requestId: string;
  debug: ChatResponsePayload["debug"];
  at: number;
} | null;

export type ChatLocale = "en" | "es";

/** Prior turns for multi-turn chat (same shape as brain ``ChatRequest.history``). */
export type ChatHistoryTurn = { role: "user" | "assistant"; content: string };

/** One SSE JSON payload from ``POST /agent/chat/stream`` (LangGraph v2 + subgraphs). */
export type ChatStreamEvent =
  | { event: "start"; request_id: string }
  | {
      event: "token";
      source: "main" | "subagent";
      text?: string;
      ns?: string[];
    }
  | { event: "step"; source: "main" | "subagent"; node: string; ns?: string[] }
  | {
      event: "tool_delta";
      source: "main" | "subagent";
      tool_name?: string;
      args_fragment?: string;
      ns?: string[];
    }
  | {
      event: "done";
      reply: string;
      subagent_reply: string;
      request_id: string;
      debug?: Record<string, unknown> | null;
    }
  | { event: "error"; message: string; request_id: string };

/**
 * Stream an agent turn (SSE). Calls ``onEvent`` for each JSON object; resolves when the stream ends.
 * The server usually ends with ``done`` or ``error``.
 */
export async function postChatStream(
  message: string,
  options: {
    locale?: ChatLocale;
    /** Completed turns before ``message`` (user + assistant pairs). */
    history?: ChatHistoryTurn[];
    signal?: AbortSignal;
    onEvent: (ev: ChatStreamEvent) => void;
  },
): Promise<void> {
  const locale = options.locale === "es" ? "es" : "en";
  const history = options.history ?? [];
  const userSignal = options.signal;
  const ctrl = new AbortController();
  const to = window.setTimeout(() => ctrl.abort(), CHAT_FETCH_MS);
  if (userSignal) {
    if (userSignal.aborted) {
      window.clearTimeout(to);
      throw new DOMException("Aborted", "AbortError");
    }
    userSignal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(to);
        ctrl.abort();
      },
      { once: true },
    );
  }
  const dec = new TextDecoder();
  let buf = "";
  try {
    const res = await brainFetch(brainApiUrl("/agent/chat/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, locale, history }),
      signal: ctrl.signal,
    });
    const t0 = performance.now();
    if (import.meta.env.DEV) {
      console.info(
        "[datasyn] POST /agent/chat/stream",
        res.status,
        res.headers.get("X-Request-ID"),
        `${Math.round(performance.now() - t0)}ms (headers)`,
      );
    }
    if (!res.ok) {
      throw new Error(await readFetchError(res));
    }
    const reader = res.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const blocks = buf.split("\n\n");
      buf = blocks.pop() ?? "";
      for (const block of blocks) {
        for (const line of block.split("\n")) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload) continue;
          try {
            const ev = JSON.parse(payload) as ChatStreamEvent;
            options.onEvent(ev);
          } catch {
            /* ignore malformed chunk */
          }
        }
      }
    }
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error(
        `Chat stream aborted or timed out after ${CHAT_FETCH_MS / 1000}s (see api.ts CHAT_FETCH_MS).`,
      );
    }
    throw e;
  } finally {
    window.clearTimeout(to);
  }
}

export async function postChat(
  message: string,
  options?: { locale?: ChatLocale; history?: ChatHistoryTurn[] },
): Promise<ChatResponsePayload> {
  const locale = options?.locale === "es" ? "es" : "en";
  const history = options?.history ?? [];
  const ctrl = new AbortController();
  const t = window.setTimeout(() => ctrl.abort(), CHAT_FETCH_MS);
  const t0 = performance.now();
  try {
    const res = await brainFetch(brainApiUrl("/agent/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, locale, history }),
      signal: ctrl.signal,
    });
    if (import.meta.env.DEV) {
      console.info(
        "[datasyn] POST /agent/chat",
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

export async function readFetchError(res: Response): Promise<string> {
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
  /** `litellm` (default), `openrouter`, or `gemini` — see brain `MODEL_PROVIDER`. */
  model_provider?: string;
  litellm_base?: string | null;
  has_key?: boolean;
  /** Last 4 chars of `LITELLM_KEY` loaded by the brain (compare to LiteLLM 401 messages like `...RbPw`). */
  litellm_key_suffix?: string | null;
  /** OpenRouter API base (default `https://openrouter.ai/api/v1` when using `MODEL_PROVIDER=openrouter`). */
  openrouter_base?: string | null;
  has_openrouter_key?: boolean;
  openrouter_key_suffix?: string | null;
  /** If set, LangChain may read `OPENAI_API_KEY` for other code paths; ChatOpenAI uses `LITELLM_KEY` explicitly. */
  openai_api_key_env_set?: boolean;
  openai_api_key_env_suffix?: string | null;
  in_docker?: boolean;
  chat_model?: string;
  chat_model_env?: string;
  chat_model_source?: "env" | "runtime";
  /** Same object as ``GET /health/pipeline``; embedded so the UI needs only one request. */
  pipeline?: Record<string, unknown>;
};

export type OpenRouterModelItem = {
  id: string;
  name: string;
  description?: string;
  context_length?: number | null;
  is_free?: boolean;
};

export type OpenRouterModelsResponse = {
  status: string;
  model_provider?: string;
  models: OpenRouterModelItem[];
  count?: number;
  free_only?: boolean;
  error?: string | null;
};

export type ChatModelUpdateResponse = {
  status: string;
  chat_model: string;
  chat_model_env?: string;
  chat_model_source?: "env" | "runtime";
  model_provider?: string;
};

export type ToolInventoryItem = {
  name: string;
  server: string;
  source: "mcp" | "helper";
};

export type SkillInventoryItem = {
  source: "skill";
  name: string;
  path: string;
};

export type ToolInventoryResponse = {
  status: string;
  tools: ToolInventoryItem[];
  skills: SkillInventoryItem[];
  mcp_error?: string | null;
};

export type LlmConfig = {
  model_provider?: string;
  litellm_base: string | null;
  openrouter_base?: string | null;
  has_key: boolean;
  has_openrouter_key?: boolean;
  litellm_key_suffix: string | null;
  openrouter_key_suffix?: string | null;
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
  const res = await brainFetch(brainApiUrl("/health"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<BrainHealth>;
}

/** Derive LLM block from expanded ``GET /health`` (new brains). */
export function llmConfigFromHealth(h: BrainHealth): LlmConfig | null {
  if (h.litellm_base === undefined && h.chat_model === undefined) {
    return null;
  }
  return {
    model_provider: h.model_provider,
    litellm_base: h.litellm_base ?? null,
    openrouter_base: h.openrouter_base ?? null,
    has_key: Boolean(h.has_key),
    has_openrouter_key: Boolean(h.has_openrouter_key),
    litellm_key_suffix:
      typeof h.litellm_key_suffix === "string" ? h.litellm_key_suffix : null,
    openrouter_key_suffix:
      typeof h.openrouter_key_suffix === "string" ? h.openrouter_key_suffix : null,
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
  const res = await brainFetch(brainApiUrl("/health/llm/config"));
  if (!res.ok) throw new Error(await readFetchError(res));
  const raw = (await res.json()) as Record<string, unknown>;
  return {
    model_provider: raw.model_provider as string | undefined,
    litellm_base: (raw.litellm_base as string | null) ?? null,
    openrouter_base: (raw.openrouter_base as string | null) ?? null,
    has_key: Boolean(raw.has_key),
    has_openrouter_key: Boolean(raw.has_openrouter_key),
    litellm_key_suffix:
      typeof raw.litellm_key_suffix === "string" ? raw.litellm_key_suffix : null,
    openrouter_key_suffix:
      typeof raw.openrouter_key_suffix === "string" ? raw.openrouter_key_suffix : null,
    openai_api_key_env_set: Boolean(raw.openai_api_key_env_set),
    openai_api_key_env_suffix:
      typeof raw.openai_api_key_env_suffix === "string" ? raw.openai_api_key_env_suffix : null,
    in_docker: Boolean(raw.in_docker),
    chat_model: String(raw.chat_model ?? ""),
  };
}

export async function probeLlm(): Promise<unknown> {
  const res = await brainFetch(brainApiUrl("/health/llm"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json();
}

export async function getOpenRouterModels(options?: {
  freeOnly?: boolean;
  refresh?: boolean;
}): Promise<OpenRouterModelsResponse> {
  const params = new URLSearchParams();
  if (options?.freeOnly) params.set("free_only", "true");
  if (options?.refresh) params.set("refresh", "true");
  const qs = params.toString();
  const res = await brainFetch(brainApiUrl(`/health/llm/models${qs ? `?${qs}` : ""}`));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<OpenRouterModelsResponse>;
}

export async function setChatModel(chatModel: string): Promise<ChatModelUpdateResponse> {
  const res = await brainFetch(brainApiUrl("/health/llm/model"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_model: chatModel }),
  });
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<ChatModelUpdateResponse>;
}

/**
 * Optional alias: same JSON as ``GET /health`` → ``pipeline`` (older brains may 404 — prefer ``pipeline`` on health).
 */
export async function getHealthPipeline(): Promise<Record<string, unknown> | null> {
  const res = await brainFetch(brainApiUrl("/health/pipeline"));
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<Record<string, unknown>>;
}

export async function getToolsInventory(): Promise<ToolInventoryResponse> {
  const res = await brainFetch(brainApiUrl("/health/tools"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<ToolInventoryResponse>;
}

/** Row from ``duckdb_get_schema`` grouped under a medallion schema. */
export type WarehouseLayerTable = {
  name: string;
  table_type: string;
};

export type WarehouseOtherTable = {
  schema: string;
  name: string;
  table_type: string;
};

/** ``GET /health/warehouse/tables`` — tables in bronze/silver/gold plus other schemas. */
export type WarehouseTablesResponse = {
  status: string;
  layers: {
    bronze: WarehouseLayerTable[];
    silver: WarehouseLayerTable[];
    gold: WarehouseLayerTable[];
  };
  other: WarehouseOtherTable[];
  raw_line_count?: number;
  error?: string | null;
};

export async function getWarehouseTables(): Promise<WarehouseTablesResponse> {
  const res = await brainFetch(brainApiUrl("/health/warehouse/tables"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<WarehouseTablesResponse>;
}

export type DagsterMetadataEntry = {
  label: string;
  type?: string;
  value: string | number | boolean;
};

export type DagsterLatestMaterialization = {
  run_id?: string | null;
  timestamp?: string | null;
  partition?: string | null;
  metadata?: DagsterMetadataEntry[];
};

export type CatalogDatasetCard = {
  fqn: string;
  schema: string;
  name: string;
  layer: string;
  table_type?: string | null;
  description?: string | null;
  column_count?: number | null;
  tags?: string[];
  owners?: string[];
  lineage?: string[];
  lineage_upstream?: string[];
  lineage_downstream?: string[];
  dagster_job?: string | null;
  dagster_jobs?: string[];
  dagster_group?: string | null;
  dagster_asset_key?: string | null;
  dagster_asset_path?: string[];
  dagster_table_fqn?: string | null;
  dagster_compute_kind?: string | null;
  dagster_kinds?: string[];
  dagster_owners?: string[];
  dagster_is_partitioned?: boolean;
  dagster_latest_materialization?: DagsterLatestMaterialization | null;
  dagster_definition_metadata?: DagsterMetadataEntry[];
  dagster_only?: boolean;
  last_updated?: string | null;
  in_warehouse: boolean;
  in_catalog: boolean;
  in_dagster?: boolean;
};

export type CatalogDatasetsResponse = {
  status: string;
  catalog_status?: string;
  dagster_status?: string;
  dagster_error?: string | null;
  dagster_url?: string | null;
  dagster_graphql_url?: string | null;
  warehouse_tables?: string[];
  datasets: CatalogDatasetCard[];
  count?: number;
  error?: string | null;
};

export type CatalogColumnRow = {
  name: string;
  type: string;
  description?: string;
};

export type CatalogDatasetDetailResponse = {
  status: string;
  dataset?: CatalogDatasetCard | null;
  catalog_columns?: CatalogColumnRow[];
  warehouse_columns?: CatalogColumnRow[];
  dagster?: Record<string, unknown> | null;
  dagster_url?: string | null;
  dagster_graphql_url?: string | null;
  lineage?: { upstream?: string[]; downstream?: string[] };
  error?: string | null;
};

export async function getCatalogDatasets(options?: {
  duckdbTable?: string | null;
}): Promise<CatalogDatasetsResponse> {
  const params = new URLSearchParams();
  if (options?.duckdbTable) {
    params.set("duckdb_table", options.duckdbTable);
  }
  const qs = params.toString();
  const res = await brainFetch(brainApiUrl(`/catalog/datasets${qs ? `?${qs}` : ""}`));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<CatalogDatasetsResponse>;
}

export async function getCatalogDatasetDetail(fqn: string): Promise<CatalogDatasetDetailResponse> {
  const enc = encodeURIComponent(fqn);
  const res = await brainFetch(brainApiUrl(`/catalog/datasets/${enc}`));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<CatalogDatasetDetailResponse>;
}

export type AnalysisManifest = {
  id: string;
  title: string;
  created_at: string;
  dataset_fqn?: string | null;
  preview: string;
  message_count: number;
  report_path: string;
  locale?: string;
};

export type AnalysesListResponse = {
  status: string;
  analyses: AnalysisManifest[];
  count: number;
};

export type AnalysisDetailResponse = {
  status: string;
  manifest: AnalysisManifest;
  report_md: string;
};

export type AnalysisExportRequest = {
  messages: { role: "user" | "assistant"; content: string }[];
  locale?: ChatLocale;
  title?: string | null;
  dataset_fqn?: string | null;
  request_ids?: string[];
};

export async function listAnalyses(): Promise<AnalysesListResponse> {
  const res = await brainFetch(brainApiUrl("/analyses"));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<AnalysesListResponse>;
}

export async function getAnalysis(id: string): Promise<AnalysisDetailResponse> {
  const res = await brainFetch(brainApiUrl(`/analyses/${encodeURIComponent(id)}`));
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<AnalysisDetailResponse>;
}

export async function exportAnalysis(body: AnalysisExportRequest): Promise<{ status: string; analysis: AnalysisManifest }> {
  const res = await brainFetch(brainApiUrl("/analyses/export"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: body.messages,
      locale: body.locale ?? "en",
      title: body.title ?? null,
      dataset_fqn: body.dataset_fqn ?? null,
      request_ids: body.request_ids ?? [],
    }),
  });
  if (!res.ok) throw new Error(await readFetchError(res));
  return res.json() as Promise<{ status: string; analysis: AnalysisManifest }>;
}

