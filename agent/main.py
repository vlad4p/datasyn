"""HTTP control plane for the Datacyber Deep Agent (leader).

The leader loads MCP HTTP tool servers from ``mcp.json`` at the project root
(warehouse ``duckdb-mcp``, data catalog ``catalog-mcp`` backed by MongoDB).
The warehouse worker remains a separate HTTP service (``WAREHOUSE_API_URL``).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agent.utils.agent_chat import run_agent_chat_turn
from agent.utils.langfuse_tracing import (
    langfuse_tracing_enabled,
    log_langfuse_docker_loopback_hint,
)
from agent.utils.catalog_mcp import fetch_catalog_datasets_via_mcp
from agent.utils.litellm_chat import (
    explain_litellm_http_exception,
    probe_litellm_proxy,
    running_in_docker,
)
from agent.config import (
    ENV_DOTENV_LOADED_AT_IMPORT,
    ENV_DOTENV_RESOLVED_PATH,
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


_configure_logging()


def _log_effective_llm_env() -> None:
    """One-line proof of which LiteLLM key/model the process actually loaded (suffix matches proxy error snippets)."""
    key = settings.litellm_key or ""
    if len(key) > 12:
        masked = f"{key[:7]}...{key[-4:]}"
    elif key:
        masked = "(set, short)"
    else:
        masked = "(unset)"
    logger.info(
        "Effective LLM env: CHAT_MODEL=%r LITELLM_TEMPERATURE=%s LITELLM_KEY=%s LITELLM_BASE=%r",
        settings.chat_model,
        os.environ.get("LITELLM_TEMPERATURE", "(unset)"),
        masked,
        settings.litellm_api_base,
    )


_log_effective_llm_env()
log_langfuse_docker_loopback_hint()


def _litellm_connection_error_hint() -> str:
    """Extra context when ChatOpenAI cannot reach LiteLLM (port down, wrong host for Docker, etc.)."""
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
    title="Datacyber",
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
    *settings.cors_extra_origins,
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Outermost runs first: strip `/api` before routing so `/api/health` matches `GET /health`.
app.add_middleware(StripApiPrefixMiddleware)


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


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    reply: str
    request_id: str = Field(
        ...,
        description="Correlation id for brain/MCP/LiteLLM logs; echoed as X-Request-ID.",
    )
    debug: dict[str, Any] | None = Field(
        None,
        description="Structured pipeline trace when brain has DATACYBER_PIPELINE_DEBUG=1.",
    )


def _llm_config_snapshot() -> dict[str, Any]:
    """Static LiteLLM settings (no network)."""
    key = settings.litellm_key or ""
    # Last 4 chars — compare to LiteLLM 401 messages (`...RbPw` vs current key) without exposing the full secret.
    key_suffix = key[-4:] if len(key) >= 8 else None
    oai = (os.getenv("OPENAI_API_KEY") or "").strip()
    oai_suffix = oai[-4:] if len(oai) >= 8 else None
    return {
        "litellm_base": settings.litellm_api_base,
        "has_key": bool(settings.litellm_key),
        "litellm_key_suffix": key_suffix,
        "openai_api_key_env_set": bool(oai),
        "openai_api_key_env_suffix": oai_suffix,
        "in_docker": running_in_docker(),
        "chat_model": settings.chat_model,
        "langfuse_tracing_enabled": langfuse_tracing_enabled(),
    }


def _mcp_urls_public() -> dict[str, str]:
    """URLs from mcp.json (for debugging; no secrets)."""
    cfg = settings.project_root / "mcp.json"
    if not cfg.is_file():
        return {}
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
        block = raw.get("mcpServers") or raw.get("servers") or {}
        out: dict[str, str] = {}
        if isinstance(block, dict):
            for name, spec in block.items():
                if isinstance(spec, dict) and spec.get("url"):
                    out[str(name)] = str(spec["url"])
        return out
    except Exception as exc:
        return {"_error": str(exc)}


def _pipeline_snapshot() -> dict[str, Any]:
    """Architecture snapshot: who lists /data-local, MCP URLs, debug flags (no secrets)."""
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
                "(e.g. `datacyber/.env`). In Docker with this compose file, mount host `./.env` → `/project/.env` "
                "and keep `PROJECT_ROOT=/project` so this path matches.",
                "compose_also_injects": "docker-compose `brain.env_file`: compose.env then .env (values frozen until "
                "container recreate; bind-mounted `.env` is re-read on every Python import via load_dotenv).",
            },
        },
        "mcp_servers": _mcp_urls_public(),
        "listing_data_local": {
            "filesystem_tool": "duckdb-mcp exposes `data_local_ls(path)` — read-only directory listing under DATA_LOCAL_ROOT (default /data-local).",
            "who_runs_glob": "duckdb-mcp `warehouse_query` runs DuckDB SQL; `glob()` reads the container filesystem.",
            "brain_mounts_data_local": False,
            "duckdb_service_mounts_data_local": True,
            "duckdb_mcp_mounts_data_local": True,
            "ui_lists_files": False,
        },
        "skills": {
            "where": "./skills/ingest-csv/SKILL.md",
            "how": "Deep Agents `skills=[\"/skills/ingest-csv\"]` on create_deep_agent. "
            "See also `./skills/langfuse/` (Langfuse observability skill for maintainers; not agent-injected).",
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness, LLM snapshot, and pipeline/architecture info (UI uses one request via ``GET /api/health``)."""
    return {
        "status": "ok",
        **_llm_config_snapshot(),
        "pipeline": _pipeline_snapshot(),
    }


@app.get("/health/llm/config")
def health_llm_config() -> dict[str, Any]:
    """Same fields as the LLM keys on ``GET /health`` (kept for scripts and older clients)."""
    return _llm_config_snapshot()


@app.get("/health/pipeline")
def health_pipeline() -> dict[str, Any]:
    """Same payload as the ``pipeline`` key on ``GET /health`` (alias for scripts and curl)."""
    return _pipeline_snapshot()


@app.get("/catalog/datasets")
async def catalog_datasets(
    limit: int = Query(48, ge=1, le=200),
    service_name: str = Query("", max_length=128),
    database_name: str = Query("", max_length=128),
    schema_name: str = Query("", max_length=128),
) -> dict[str, Any]:
    """UI catalog refresh: invoke ``catalog_list_datasets`` via MCP (same stack as the Deep Agent)."""
    try:
        return await fetch_catalog_datasets_via_mcp(
            limit=limit,
            service_name=service_name,
            database_name=database_name,
            schema_name=schema_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("catalog MCP: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/health/llm")
async def health_llm() -> dict:
    """Probe LiteLLM (GET /v1/models). Use when /agent/chat returns connection errors."""
    try:
        return await probe_litellm_proxy()
    except Exception as exc:
        logger.exception("health/llm probe failed")
        return {"ok": False, "error": str(exc)[:500], "litellm_base": settings.litellm_api_base}


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
    try:
        result = await run_agent_chat_turn(
            body.message,
            request_id=request_id,
            langfuse_session_id=session_id,
            langfuse_user_id=user_id,
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


if __name__ == "__main__":
    run()
