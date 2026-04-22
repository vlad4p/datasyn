# Pipeline: UI → brain → LiteLLM → MCP (duckdb-mcp) → `/data-local`

## Who does what (no `ls` anywhere)

| Layer | Responsibility |
|--------|----------------|
| **Vite dev server** (`npm run dev`) | Serves the React app; **proxies** `/api/*` to the brain (`vite.config.ts` → `VITE_PROXY_TARGET`, default `http://127.0.0.1:8002` = Docker host port for `brain`). The browser never talks to Docker service names (`brain`, `duckdb-mcp`). |
| **UI (React)** | `POST /api/agent/chat` → brain. Does **not** read `./data-local` from disk. |
| **Brain (`agent.main`)** | Loads **`mcp.json`**, connects to MCP over HTTP, runs the LangGraph/deep agent, calls **LiteLLM** for the model. **Does not mount `data-local`.** |
| **LiteLLM (or compatible OpenAI API)** | LLM inference only. |
| **duckdb-mcp** | Exposes **`warehouse_list_tables`**, **`warehouse_query`**, and **`data_local_ls`** (read-only directory listing under `DATA_LOCAL_ROOT`, default `/data-local`). SQL runs **inside this container**. DuckDB **`glob()`** also reads **this process’s filesystem** — hence **`./data-local` must be mounted here** (see `mcp_servers/docker-compose.yaml`). |
| **`duckdb` service** | Holds **`warehouse.duckdb`** on volume `duckdb_data`; mounts `./data-local` for workflows that use the DB container directly. **Listing files for the chat agent does not use this service’s shell** — listing is SQL `glob` in **duckdb-mcp**. |
| **Skills (`./skills/*/SKILL.md`)** | **Runtime:** Deep Agents loads **`skills=["/skills/ingest-csv"]`** in `agent/graph.py` for ingest workflows. **`./skills/langfuse/`** is maintainer/docs only (not injected into the agent). Not a separate microservice; no HTTP “skill server.” |

## Verifying “list files” is correct

1. **Ground truth on the host:** `ls data-local/EPH_usu_3_Trim_2025_txt` (or your folder).
2. **MCP tools (inside duckdb-mcp):** call **`data_local_ls`** with path `/data-local/EPH_usu_3_Trim_2025_txt` (or `EPH_usu_3_Trim_2025_txt`).  
   Alternatively: `SELECT file FROM glob('/data-local/EPH_usu_3_Trim_2025_txt/*');`  
   Top-level only: `glob('/data-local/*')` — does **not** expand nested folders.
3. **Brain introspection:** `GET /health` includes a **`pipeline`** object (same JSON as `GET /health/pipeline`). The UI uses a single health request; **`GET /health/pipeline`** remains an alias for scripts.

## Logs (operations)

| Where | What |
|--------|------|
| **Brain stderr** | `POST /agent/chat`, `request_id`, MCP tool names, `agent.ainvoke` timing, per-message timeline (see `agent/utils/agent_chat.py`). |
| **duckdb-mcp stderr** | Each `warehouse_query` / `warehouse_list_tables` with SQL preview, duration, row counts (`mcp_servers/duckdb-mcp/server.py`). |
| **UI devtools console** | `[datacyber] POST /agent/chat` status, `X-Request-ID`, duration (`ui/src/api.ts`, dev only). |

## Optional JSON debug in chat responses

Set on the **brain** environment:

```bash
DATACYBER_PIPELINE_DEBUG=1
```

Restart the brain. Responses include a **`debug`** object (steps, tool names, message timeline). The UI shows it under **Dashboard → Last chat** when present.

## Optional Langfuse tracing

Set **`LANGFUSE_PUBLIC_KEY`** and **`LANGFUSE_SECRET_KEY`** on the brain (see `compose.env` comments). Traces use the LangChain callback and correlate with **`X-Request-ID`**. Optionally send **`X-Langfuse-Session-Id`** and **`X-Langfuse-User-Id`** on `POST /agent/chat` for sessions and user attribution. `GET /health` includes **`langfuse_tracing_enabled`**.

If the brain runs in **Docker** and Langfuse is on the **host** (typical local self-hosted on port 3000), set **`LANGFUSE_BASE_URL=http://host.docker.internal:3000`**, not `http://localhost:3000` — inside the container, `localhost` is not your Mac/host.

## If the UI “never responds”

- **Proxy timeout:** Vite `/api` proxy uses **600s** for long agent turns. Earlier defaults could close the connection before the brain returns.
- **LiteLLM down:** `GET /api/health/llm` or **Probe LiteLLM** in the Dashboard.
- **Empty reply:** Check brain logs for `empty assistant reply`; `resolve_assistant_reply` walks back through AIMessages if the last graph message is not assistant text.
