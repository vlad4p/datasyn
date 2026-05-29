"""Require a valid session for API routes when auth is enabled."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agent.auth.config import auth_settings
from agent.auth.session import user_from_request

_PUBLIC_PREFIXES = ("/health", "/auth")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not auth_settings.enabled:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path or ""
        if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)
        if user_from_request(request) is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        return await call_next(request)
