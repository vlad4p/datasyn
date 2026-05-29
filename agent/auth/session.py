"""Signed JWT session cookie helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, Request, Response

from agent.auth import config as auth_config

SESSION_COOKIE = "datasyn_session"
ALGORITHM = "HS256"


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    name: str | None
    picture: str | None
    provider: str

    def as_public_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
            "provider": self.provider,
        }


def _secret() -> str:
    secret = auth_config.auth_settings.session_secret
    if not secret:
        raise RuntimeError("OAUTH_SESSION_SECRET is required when auth is enabled")
    return secret


def create_session_token(user: AuthUser) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "provider": user.provider,
        "iat": now,
        "exp": now + timedelta(seconds=auth_config.auth_settings.session_max_age_seconds),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_session_token(token: str) -> AuthUser | None:
    if not token or not auth_config.auth_settings.session_secret:
        return None
    try:
        payload = jwt.decode(
            token,
            auth_config.auth_settings.session_secret,
            algorithms=[ALGORITHM],
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    provider = payload.get("provider")
    if not sub or not provider:
        return None
    return AuthUser(
        id=str(sub),
        email=_optional_str(payload.get("email")),
        name=_optional_str(payload.get("name")),
        picture=_optional_str(payload.get("picture")),
        provider=str(provider),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def user_from_request(request: Request) -> AuthUser | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return decode_session_token(token)


def set_session_cookie(response: Response, user: AuthUser) -> None:
    token = create_session_token(user)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=auth_config.auth_settings.session_max_age_seconds,
        httponly=True,
        secure=auth_config.auth_settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=auth_config.auth_settings.secure_cookies,
        samesite="lax",
    )


def require_auth_user(request: Request) -> AuthUser:
    user = user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
