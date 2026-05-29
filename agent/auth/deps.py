"""FastAPI dependencies for optional/required authentication."""

from __future__ import annotations

from fastapi import Request

from agent.auth.config import auth_settings
from agent.auth.session import AuthUser, require_auth_user, user_from_request


def require_user(request: Request) -> AuthUser | None:
    """Return the authenticated user when auth is enabled; otherwise ``None``."""
    if not auth_settings.enabled:
        return None
    return require_auth_user(request)


def optional_user(request: Request) -> AuthUser | None:
    if not auth_settings.enabled:
        return None
    return user_from_request(request)
