"""HTTP control plane for the Datasyn Deep Agent (leader).

The leader loads MCP HTTP tool servers from ``mcp.json`` at the project root
(warehouse ``duckdb-mcp``, ``storage-mcp``, ``dagster-mcp``, etc.).
The warehouse worker remains a separate HTTP service (``WAREHOUSE_API_URL``).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import AliasChoices, BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agent.auth import auth_router
from agent.auth.config import auth_settings
from agent.auth.middleware import AuthMiddleware
from agent.auth.deps import optional_user
from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient

from agent.utils.agent_chat import run_agent_chat_turn, stream_agent_chat_sse_events
from agent.utils.langfuse_tracing import (
    langfuse_tracing_enabled,
    log_langfuse_docker_loopback_hint,
)
from agent.utils.mcp_connections import load_mcp_tool_connections
from agent.utils.otel_tracing import init_otel_tracing
from agent.utils.analysis_export import export_analysis, get_analysis, list_analyses
from agent.utils.dagster_graphql import dagster_graphql_url, dagster_server_url
from agent.utils.catalog_datasets import catalog_dataset_detail_payload, catalog_datasets_payload
from agent.utils.warehouse_schema import warehouse_tables_payload
from agent.utils.litellm_chat import (
    explain_litellm_http_exception,
    probe_litellm_proxy,
    running_in_docker,
)
from agent.utils.chat_model_state import (
    chat_model_source,
    effective_chat_model,
    set_runtime_chat_model,
)
from agent.utils.openrouter_models import list_openrouter_models
from agent.config import (
    ENV_DOTENV_LOADED_AT_IMPORT,
    ENV_DOTENV_RESOLVED_PATH,
    OPENROUTER_DEFAULT_API_BASE,
    settings,
)

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
        force=True,
    )
    _silence_langchain_genai_schema_key_warnings()


def _silence_langchain_genai_schema_key_warnings() -> None:
    """``langchain_google_genai`` warns per JSON Schema key Gemini omits (e.g. ``additionalProperties``). Tools still work; noise only."""

    class _DropUnsupportedSchemaKeyWarning(logging.Filter):
        _needle = "not supported in schema, ignoring"

        def filter(self, record: logging.LogRecord) -> bool:
            if not record.name.startswith("langchain_google_genai."):
                return True
            try:
                msg = record.getMessage()
            except Exception:
                return True
            return self._needle not in msg

    lg = logging.getLogger("langchain_google_genai._function_utils")
    lg.addFilter(_DropUnsupportedSchemaKeyWarning())
    # Same messages can propagate via parent loggers depending on config.
    lg.propagate = True


_configure_logging()
init_otel_tracing()


def _log_effective_llm_env() -> None:
    """One-line proof of which LLM key/model the process loaded."""
    if settings.model_provider == "gemini":
        key = settings.gemini_api_key or ""
        if len(key) > 12:
            masked = f"{key[:7]}...{key[-4:]}"
        elif key:
            masked = "(set, short)"
        else:
            masked = "(unset)"
        logger.info(
            "Effective LLM env: MODEL_PROVIDER=gemini CHAT_MODEL=%r GEMINI_API_KEY=%s",
            settings.chat_model,
            masked,
        )
        return
    if settings.model_provider == "openrouter":
        key = settings.openrouter_api_key or ""
        if len(key) > 12:
            masked = f"{key[:7]}...{key[-4:]}"
        elif key:
            masked = "(set, short)"
        else:
            masked = "(unset)"
        logger.info(
            "Effective LLM env: MODEL_PROVIDER=openrouter CHAT_MODEL=%r LITELLM_TEMPERATURE=%s "
            "OPENROUTER_API_KEY=%s OPENROUTER_BASE=%r",
            settings.chat_model,
            os.environ.get("LITELLM_TEMPERATURE", "(unset)"),
            masked,
            settings.openrouter_api_base or OPENROUTER_DEFAULT_API_BASE,
        )
        return
    key = settings.litellm_key or ""
    if len(key) > 12:
        masked = f"{key[:7]}...{key[-4:]}"
    elif key:
        masked = "(set, short)"
    else:
        masked = "(unset)"
    logger.info(
        "Effective LLM env: MODEL_PROVIDER=litellm CHAT_MODEL=%r LITELLM_TEMPERATURE=%s LITELLM_KEY=%s LITELLM_BASE=%r",
        settings.chat_model,
        os.environ.get("LITELLM_TEMPERATURE", "(unset)"),
        masked,
        settings.litellm_api_base,
    )


_log_effective_llm_env()
logger.info(
    "Effective Dagster: DAGSTER_URL=%r graphql=%r",
    settings.dagster_url,
    dagster_graphql_url(),
)
log_langfuse_docker_loopback_hint()


def _litellm_connection_error_hint() -> str:
    """Extra context when ChatOpenAI cannot reach LiteLLM (port down, wrong host for Docker, etc.)."""
    if settings.model_provider == "gemini":
        return (
            "MODEL_PROVIDER=gemini uses Google AI directly; LiteLLM loopback hints do not apply. "
            "Verify GEMINI_API_KEY and CHAT_MODEL (optional; defaults to gemini-2.0-flash)."
        )
    if settings.model_provider == "openrouter":
        return (
            "MODEL_PROVIDER=openrouter uses OpenRouter's HTTPS API (OPENROUTER_BASE_URL or "
            f"{OPENROUTER_DEFAULT_API_BASE}). Verify OPENROUTER_API_KEY, CHAT_MODEL "
            "(see https://openrouter.ai/models), and outbound TLS from this process."
        )
    base = (settings.litellm_api_base or "").lower()
    in_container = running_in_docker()
    bits = [
        f"resolved_litellm_base={settings.litellm_api_base!r}",
        f"brain_in_docker={in_container}",
    ]
    if "127.0.0.1" in base or "localhost" in base:
        if not in_container:
            bits.append(
                "The brain runs on the host and targets loopback — start LiteLLM on this machine: "
                "`litellm --host 0.0.0.0 --port 4000` (or fix LITELLM_PROXY_BASE to where your proxy listens)."
            )
        else:
            bits.append(
                "If you see loopback inside Docker, set LITELLM_PROXY_BASE=http://host.docker.internal:4000 "
                "or ensure LITELLM_DOCKER_HOST_REWRITE=1 (default)."
            )
    elif "host.docker.internal" in base:
        bits.append(
            "Brain is in Docker; LiteLLM must run on the host bound to 0.0.0.0:4000 (not 127.0.0.1-only)."
        )
    bits.append("Quick check: `curl -sS http://127.0.0.1:4000/v1/models -H \"Authorization: Bearer $LITELLM_KEY\"` from the host.")
    return " ".join(bits)


def _format_agent_error(exc: BaseException) -> str:
    """Flatten ExceptionGroup (LangGraph / asyncio) for HTTP JSON detail."""
    subs = getattr(exc, "exceptions", None)
    if subs and type(exc).__name__ in ("ExceptionGroup", "BaseExceptionGroup"):
        return "; ".join(_format_agent_error(e) for e in subs)
    return f"{type(exc).__name__}: {exc}"


app = FastAPI(
    title="Datasyn",
    description=(
        "Leader agent API. Remote tools use HTTP endpoints listed in mcp.json "
        "(mcpServers block)."
    ),
)


class StripApiPrefixMiddleware:
    """Vite proxy targets `/api/*` → backend; strip prefix so `GET /api/health` maps to `GET /health`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path") or ""
            if path.startswith("/api"):
                rest = path[4:]
                new_path = rest if (rest.startswith("/") or not rest) else f"/{rest}"
                if not new_path:
                    new_path = "/"
                scope = {
                    **scope,
                    "path": new_path,
                    "raw_path": new_path.encode("utf-8"),
                }
        await self.app(scope, receive, send)


# React UI often runs on the host (`npm run dev`), brain in Docker (`8000:8000`). Default origins
# cover Vite; add CORS_EXTRA_ORIGINS=http://192.168.x.x:5173 if you open the UI from another host.
_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:8003",
    "http://127.0.0.1:8003",
    *settings.cors_extra_origins,
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if auth_settings.enabled and auth_settings.session_secret:
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=auth_settings.session_secret)
# Outermost runs first: strip `/api` before routing so `/api/health` matches `GET /health`.
app.add_middleware(StripApiPrefixMiddleware)

app.include_router(auth_router)


@app.exception_handler(HTTPException)
async def http_exception_handler_wrapper(request: Request, exc: HTTPException):
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log full traceback; return JSON detail (avoids opaque 'Internal Server Error' in the UI)."""
    logger.exception("%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": _format_agent_error(exc)},
    )


class ChatHistoryTurn(BaseModel):
    """Prior turns only (excludes the current ``message``); maps to HumanMessage / AIMessage."""

    role: Literal["user", "assistant"]
    content: str = Field(default="", description="Plain text body for this role.")


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("message", "user_message"),
    )
    locale: Literal["en", "es"] = Field(
        "en",
        description="Assistant reply language: English or Spanish (UI ES/EN selector).",
    )
    history: list[ChatHistoryTurn] = Field(
        default_factory=list,
        description="Completed user/assistant pairs before the current user ``message``.",
    )


class ChatResponse(BaseModel):
    reply: str
    request_id: str = Field(
        ...,
        description="Correlation id for brain/MCP/LiteLLM logs; echoed as X-Request-ID.",
    )
    debug: dict[str, Any] | None = Field(
        None,
        description="Structured pipeline trace when brain has DATASYN_PIPELINE_DEBUG=1.",
    )


class AnalysisExportMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = ""


class AnalysisExportRequest(BaseModel):
    messages: list[AnalysisExportMessage] = Field(default_factory=list)
    locale: Literal["en", "es"] = "en"
    title: str | None = None
    dataset_fqn: str | None = None
    request_ids: list[str] = Field(default_factory=list)


class ChatModelUpdateRequest(BaseModel):
    chat_model: str = Field(..., min_length=1, max_length=256)


@app.get("/health/llm/models")
async def health_llm_models(
    free_only: bool = Query(False, description="When true, return only free OpenRouter models."),
    refresh: bool = Query(False, description="Bypass the in-process models cache."),
) -> dict[str, Any]:
    """OpenRouter model catalog for the UI model switch (requires MODEL_PROVIDER=openrouter)."""
    return await list_openrouter_models(free_only=free_only, force_refresh=refresh)


@app.put("/health/llm/model")
def health_llm_model_update(body: ChatModelUpdateRequest) -> dict[str, Any]:
    """Set the runtime chat model (session override; does not write ``.env``)."""
    model_id = body.chat_model.strip()
    if "*" in model_id:
        raise HTTPException(status_code=400, detail="Model id must not contain '*'")
    effective = set_runtime_chat_model(model_id)
    if not effective:
        raise HTTPException(status_code=400, detail="chat_model must be non-empty")
    logger.info("Runtime chat model set to %r (source=runtime)", effective)
    return {
        "status": "ok",
        **_llm_config_snapshot(),
    }


def _llm_config_snapshot() -> dict[str, Any]:
    """Static LLM settings (no network)."""
    key = settings.litellm_key or ""
    key_suffix = key[-4:] if len(key) >= 8 else None
    gkey = settings.gemini_api_key or ""
    gemini_suffix = gkey[-4:] if len(gkey) >= 8 else None
    or_key = settings.openrouter_api_key or ""
    or_suffix = or_key[-4:] if len(or_key) >= 8 else None
    oai = (os.getenv("OPENAI_API_KEY") or "").strip()
    oai_suffix = oai[-4:] if len(oai) >= 8 else None
    return {
        "model_provider": settings.model_provider,
        "litellm_base": settings.litellm_api_base,
        "has_key": bool(settings.litellm_key),
        "litellm_key_suffix": key_suffix,
        "gemini_key_suffix": gemini_suffix,
        "has_gemini_key": bool(settings.gemini_api_key),
        "openrouter_base": settings.openrouter_api_base or OPENROUTER_DEFAULT_API_BASE,
        "has_openrouter_key": bool(settings.openrouter_api_key),
        "openrouter_key_suffix": or_suffix,
        "openai_api_key_env_set": bool(oai),
        "openai_api_key_env_suffix": oai_suffix,
        "in_docker": running_in_docker(),
        "chat_model": effective_chat_model() or "",
        "chat_model_env": settings.chat_model or "",
        "chat_model_source": chat_model_source(),
        "langfuse_tracing_enabled": langfuse_tracing_enabled(),
        "dagster_url": settings.dagster_url,
        "dagster_graphql_url": dagster_graphql_url(),
    }


def _mcp_urls_public() -> dict[str, str]:
    """Effective MCP base URLs (after host-side rewrite when brain runs on host)."""
    try:
        conns = load_mcp_tool_connections(settings.project_root)
        return {k: str(v.get("url") or "") for k, v in conns.items()}
    except Exception as exc:
        return {"_error": str(exc)}


def _tool_connections() -> dict[str, Any]:
    """Same as chat/agent runtime — respects ``MCP_*`` env and host URL rewriting."""
    return load_mcp_tool_connections(settings.project_root)


def _skills_inventory() -> list[dict[str, str]]:
    """List all skill folders under project ``./skills`` that contain ``SKILL.md``."""
    root = settings.project_root / "skills"
    if not root.is_dir():
        return []
    out: list[dict[str, str]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            out.append(
                {
                    "name": child.name,
                    "path": f"skills/{child.name}/SKILL.md",
                }
            )
    return out


def _pipeline_snapshot() -> dict[str, Any]:
    """Architecture snapshot: MinIO landing + /data-local mirror usage, MCP URLs, debug flags."""
    duckdb_ui_public = (os.environ.get("DUCKDB_UI_PUBLIC_URL") or "").strip()
    if not duckdb_ui_public:
        port = (os.environ.get("DUCKDB_UI_PUBLISH_PORT") or "4213").strip() or "4213"
        duckdb_ui_public = f"http://127.0.0.1:{port}"
    return {
        "brain": {
            "project_root": str(settings.project_root),
            "pipeline_debug_env": settings.pipeline_debug,
            "sql_row_cap": settings.sql_row_cap,
            "dotenv": {
                "load_dotenv_path": ENV_DOTENV_RESOLVED_PATH,
                "file_existed_when_process_started": ENV_DOTENV_LOADED_AT_IMPORT,
                "load_dotenv_override_prior_env": True,
                "expected_location": "Repository root: same directory that contains the `agent/` folder "
                "(e.g. `datasyn/.env`). In Docker, `brain` uses `env_file`: `compose.env` plus optional `.env` "
                "(``path: .env`` with ``required: false``); variables are injected into the process environment.",
                "compose_also_injects": "docker-compose `brain.env_file`: compose.env then optional .env (omit .env on "
                "servers that only use compose.env / orchestrator secrets). If `/project/.env` exists in the "
                "image or a bind mount, `load_dotenv` still applies at import with override=True.",
            },
        },
        "mcp_servers": _mcp_urls_public(),
        "duckdb_ui": {
            "public_url": duckdb_ui_public,
            "compose_service": "duckdb-ui",
            "docs": "https://duckdb.org/docs/current/core_extensions/ui.html",
            "announcement": "https://duckdb.org/2025/03/12/duckdb-ui",
            "note": "Optional service: `docker compose -f infra/duckdb/docker-compose.yaml --profile ui up -d` "
            "(plain `up` omits `duckdb-ui` so duckdb-mcp can open warehouse.duckdb without lock conflicts). "
            "DuckDB binds the UI on localhost:4213 (often ::1 in-container); socat listens on 0.0.0.0:4214 "
            "(compose maps host 4213→4214).",
        },
        "listing_data_local": {
            "filesystem_tool": "duckdb-mcp exposes `list_data_mount(path)` — read-only directory listing under DATA_LOCAL_ROOT (default /data-local).",
            "who_runs_glob": "duckdb-mcp `execute_query` runs DuckDB SQL; `glob()` reads the container filesystem.",
            "landing_of_record": "MinIO object storage (`minio` service, bucket usually `data-local`) with local mirror at /data-local for DuckDB compatibility.",
            "brain_mounts_data_local": False,
            "duckdb_service_mounts_data_local": True,
            "duckdb_mcp_mounts_data_local": True,
            "ui_lists_files": False,
        },
        "skills": {
            "where": "./skills/analyze-indec-eph-hogar/SKILL.md, ./skills/analyze-news-sentimental/SKILL.md, ./skills/ingest-indec-mercadolaboral/SKILL.md, ./skills/ingest-scrape-news-bronze/SKILL.md, ./skills/scrape-indec-mercado-laboral/SKILL.md, ./skills/update-catalog/SKILL.md, ./skills/catalog-sql/SKILL.md",
            "how": "Deep Agents `skills=[\"/skills/\"]` on create_deep_agent — SkillsMiddleware treats this as a PARENT directory and auto-discovers every subdir with a SKILL.md "
            "(immediate children only; e.g. analyze-indec-eph-hogar, analyze-news-sentimental, ingest-indec-mercadolaboral, ingest-scrape-news-bronze, scrape-indec-mercado-laboral, update-catalog, catalog-sql). "
            "See also `./skills/langfuse/` (Langfuse observability skill for maintainers; no SKILL.md, not agent-injected).",
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness, LLM snapshot, and pipeline/architecture info (UI uses one request via ``GET /api/health``)."""
    return {
        "status": "ok",
        **_llm_config_snapshot(),
        "pipeline": _pipeline_snapshot(),
        "auth": {
            "enabled": auth_settings.enabled,
            "providers": list(auth_settings.providers),
        },
    }


@app.get("/health/llm/config")
def health_llm_config() -> dict[str, Any]:
    """Same fields as the LLM keys on ``GET /health`` (kept for scripts and older clients)."""
    return _llm_config_snapshot()


@app.get("/health/pipeline")
def health_pipeline() -> dict[str, Any]:
    """Same payload as the ``pipeline`` key on ``GET /health`` (alias for scripts and curl)."""
    return _pipeline_snapshot()


@app.get("/health/warehouse/tables")
async def health_warehouse_tables() -> dict[str, Any]:
    """DuckDB tables grouped by medallion schema (bronze / silver / gold) for the UI panel."""
    try:
        return await warehouse_tables_payload()
    except Exception as exc:
        logger.warning("GET /health/warehouse/tables failed: %s", exc)
        return {
            "status": "error",
            "layers": {"bronze": [], "silver": [], "gold": []},
            "other": [],
            "raw_line_count": 0,
            "error": str(exc)[:500],
        }


@app.get("/catalog/datasets")
async def catalog_datasets(
    duckdb_table: str | None = Query(None, description="Filter to one DuckDB schema.table FQN"),
) -> dict[str, Any]:
    """Merged DuckDB tables + Dagster GraphQL catalog + optional Postgres dataset_entity."""
    try:
        payload = await catalog_datasets_payload(duckdb_table=duckdb_table)
        payload["dagster_url"] = dagster_server_url()
        payload["dagster_graphql_url"] = dagster_graphql_url()
        return payload
    except Exception as exc:
        logger.warning("GET /catalog/datasets failed: %s", exc)
        return {
            "status": "error",
            "catalog_status": "error",
            "datasets": [],
            "count": 0,
            "error": str(exc)[:500],
        }


@app.get("/catalog/datasets/{fqn:path}")
async def catalog_dataset_detail(fqn: str) -> dict[str, Any]:
    """Dataset detail: catalog columns + warehouse information_schema."""
    try:
        return await catalog_dataset_detail_payload(fqn)
    except Exception as exc:
        logger.warning("GET /catalog/datasets/%s failed: %s", fqn, exc)
        return {"status": "error", "error": str(exc)[:500]}


@app.get("/analyses")
def analyses_list(limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    """List exported analysis manifests (newest first)."""
    items = list_analyses(limit=limit)
    return {"status": "ok", "analyses": items, "count": len(items)}


@app.get("/analyses/{analysis_id}")
def analyses_detail(analysis_id: str) -> dict[str, Any]:
    """Full analysis: manifest + report markdown."""
    data = get_analysis(analysis_id)
    if not data:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"status": "ok", **data}


@app.post("/analyses/export")
def analyses_export(body: AnalysisExportRequest) -> dict[str, Any]:
    """Export chat messages as a report-style analysis under reports/analyses/."""
    msgs = [m.model_dump() for m in body.messages if (m.content or "").strip()]
    if not msgs:
        raise HTTPException(status_code=400, detail="No messages to export")
    manifest = export_analysis(
        messages=msgs,
        locale=body.locale,
        title=body.title,
        dataset_fqn=body.dataset_fqn,
        request_ids=body.request_ids,
    )
    return {"status": "ok", "analysis": manifest}


@app.get("/health/tools")
async def health_tools() -> dict[str, Any]:
    """Full tool inventory for UI: all runtime MCP tools + discovered project skills."""
    mcp_tools: list[dict[str, str]] = []
    mcp_error: str | None = None
    try:
        connections = _tool_connections()
        client = MultiServerToolClient(connections, tool_name_prefix=True)
        tools = await client.get_tools()
        for t in tools:
            name = str(getattr(t, "name", "") or "").strip()
            if not name:
                continue
            server = name.split("_", 1)[0] if "_" in name else "unknown"
            mcp_tools.append({"name": name, "server": server, "source": "mcp"})
        mcp_tools = sorted(mcp_tools, key=lambda x: x["name"])
    except Exception as exc:
        mcp_error = str(exc)[:500]

    helper_tools = [
        {"name": n, "server": "deepagents", "source": "helper"}
        for n in (
            "write_todos",
            "ls",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "task",
        )
    ]
    skills = [{"source": "skill", **s} for s in _skills_inventory()]
    return {
        "status": "ok",
        "tools": mcp_tools + helper_tools,
        "skills": skills,
        "mcp_error": mcp_error,
    }


@app.get("/health/llm")
async def health_llm() -> dict:
    """Probe LiteLLM (GET /v1/models). Use when /agent/chat returns connection errors."""
    try:
        return await probe_litellm_proxy()
    except Exception as exc:
        logger.exception("health/llm probe failed")
        return {
            "ok": False,
            "error": str(exc)[:500],
            "litellm_base": settings.litellm_api_base,
            "openrouter_base": settings.openrouter_api_base or OPENROUTER_DEFAULT_API_BASE,
        }


@app.get("/artifacts/file")
def serve_project_file(
    path: str = Query(
        ...,
        min_length=1,
        max_length=1024,
        description="Path relative to PROJECT_ROOT (e.g. reports/chart.png or project/reports/chart.png).",
    ),
) -> FileResponse:
    """Serve a read-only file from the brain workspace so the React UI can display saved reports/charts."""
    root = settings.project_root.resolve()
    raw = unquote(path).strip().replace("\\", "/").lstrip("/")
    if not raw or ".." in Path(raw).parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path outside project root") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)


@app.post("/agent/chat", response_model=ChatResponse)
async def agent_chat(request: Request, response: Response, body: ChatRequest) -> ChatResponse:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    logger.info(
        "POST /agent/chat request_id=%s message_chars=%s pipeline_debug=%s",
        request_id,
        len(body.message),
        settings.pipeline_debug,
    )
    session_id = (request.headers.get("X-Langfuse-Session-Id") or "").strip() or None
    user_id = (request.headers.get("X-Langfuse-User-Id") or "").strip() or None
    auth_user = optional_user(request)
    if auth_user and not user_id:
        user_id = auth_user.id
    try:
        result = await run_agent_chat_turn(
            body.message,
            history=[h.model_dump() for h in body.history],
            request_id=request_id,
            langfuse_session_id=session_id,
            langfuse_user_id=user_id,
            response_locale=body.locale,
        )
    except Exception as exc:
        logger.exception("agent chat failed")
        msg = _format_agent_error(exc).strip() or type(exc).__name__
        litellm_hint = explain_litellm_http_exception(exc)
        if litellm_hint:
            msg = f"{msg} | {litellm_hint}"
        if "Connection error" in msg or "ConnectError" in msg or "connection attempts failed" in msg.lower():
            msg += " [" + _litellm_connection_error_hint() + "]"
        if len(msg) > 2000:
            msg = msg[:2000] + "…"
        raise HTTPException(status_code=502, detail=msg) from exc
    response.headers["X-Request-ID"] = result.request_id
    logger.info(
        "POST /agent/chat ok request_id=%s reply_chars=%s debug_payload=%s",
        result.request_id,
        len(result.reply),
        result.debug is not None,
    )
    return ChatResponse(
        reply=result.reply,
        request_id=result.request_id,
        debug=result.debug,
    )


@app.post("/agent/chat/stream")
async def agent_chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream agent run as Server-Sent Events (JSON per line, ``text/event-stream``)."""
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    session_id = (request.headers.get("X-Langfuse-Session-Id") or "").strip() or None
    user_id = (request.headers.get("X-Langfuse-User-Id") or "").strip() or None
    auth_user = optional_user(request)
    if auth_user and not user_id:
        user_id = auth_user.id
    logger.info(
        "POST /agent/chat/stream request_id=%s message_chars=%s pipeline_debug=%s",
        request_id,
        len(body.message),
        settings.pipeline_debug,
    )

    async def sse_bytes() -> AsyncIterator[bytes]:
        try:
            async for evt in stream_agent_chat_sse_events(
                body.message,
                history=[h.model_dump() for h in body.history],
                request_id=request_id,
                langfuse_session_id=session_id,
                langfuse_user_id=user_id,
                response_locale=body.locale,
            ):
                line = json.dumps(evt, ensure_ascii=False)
                yield f"data: {line}\n\n".encode("utf-8")
        except Exception as exc:
            logger.exception("agent chat stream generator failed")
            err = {"event": "error", "message": _format_agent_error(exc).strip()[:2000], "request_id": request_id}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode("utf-8")

    return StreamingResponse(
        sse_bytes(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


def run() -> None:
    import uvicorn

    uvicorn.run(
        "agent.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
        access_log=True,
    )


def dev() -> None:
    """Hot-reload dev server (``uv run brain-dev`` or ``make agent-dev-brain``)."""
    import os

    import uvicorn

    port = int(os.environ.get("API_PORT", str(settings.api_port)))
    uvicorn.run(
        "agent.main:app",
        host="127.0.0.1",
        port=port,
        reload=True,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    run()
