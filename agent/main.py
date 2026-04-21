"""HTTP control plane for the Datacyber Deep Agent (leader).

The leader loads catalog, database, and process tools over HTTP (see ``tool_servers.json``
and docker-compose). The warehouse worker remains a separate HTTP service
(``WAREHOUSE_API_URL``).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from agent.utils.agent_chat import run_agent_chat_turn
from agent.utils.litellm_chat import probe_litellm_proxy, running_in_docker
from agent.config import settings

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
        force=True,
    )


_configure_logging()


def _format_agent_error(exc: BaseException) -> str:
    """Flatten ExceptionGroup (LangGraph / asyncio) for HTTP JSON detail."""
    subs = getattr(exc, "exceptions", None)
    if subs and type(exc).__name__ in ("ExceptionGroup", "BaseExceptionGroup"):
        return "; ".join(_format_agent_error(e) for e in subs)
    return f"{type(exc).__name__}: {exc}"


app = FastAPI(
    title="Datacyber",
    description=(
        "Leader agent API. Remote tools use HTTP endpoints from tool_servers.json "
        "(Compose: catalog-tools, database-tools, process-tools)."
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


def _llm_config_snapshot() -> dict[str, Any]:
    """Static LiteLLM settings (no network)."""
    return {
        "litellm_base": settings.litellm_api_base,
        "has_key": bool(settings.litellm_key),
        "in_docker": running_in_docker(),
        "chat_model": settings.chat_model,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus LLM snapshot so the UI can use a single ``GET /api/health`` through Vite."""
    return {"status": "ok", **_llm_config_snapshot()}


@app.get("/health/llm/config")
def health_llm_config() -> dict[str, Any]:
    """Same fields as the LLM keys on ``GET /health`` (kept for scripts and older clients)."""
    return _llm_config_snapshot()


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
async def agent_chat(body: ChatRequest) -> ChatResponse:
    try:
        reply = await run_agent_chat_turn(body.message)
    except Exception as exc:
        logger.exception("agent chat failed")
        msg = _format_agent_error(exc).strip() or type(exc).__name__
        if "Connection error" in msg or "ConnectError" in msg or "connection attempts failed" in msg.lower():
            base = settings.litellm_api_base or "(not set)"
            msg += (
                f" [resolved_litellm_base={base!r}] "
                "Ensure LiteLLM is running (e.g. on host: litellm --host 0.0.0.0 --port 4000). "
                "Diagnose: curl GET /health/llm on this API, or from your machine curl the same /v1/models URL."
            )
        if len(msg) > 1200:
            msg = msg[:1200] + "…"
        raise HTTPException(status_code=502, detail=msg) from exc
    return ChatResponse(reply=reply)


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
