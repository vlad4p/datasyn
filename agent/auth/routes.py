"""OAuth login, callback, session, and logout routes."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from agent.auth.config import auth_settings
from agent.auth.providers import oauth, register_oauth_clients
from agent.auth.deps import optional_user
from agent.auth.session import (
    AuthUser,
    clear_session_cookie,
    set_session_cookie,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
register_oauth_clients()


class AuthUserPublic(BaseModel):
    id: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    provider: str


class AuthMeResponse(BaseModel):
    auth_enabled: bool
    authenticated: bool
    user: AuthUserPublic | None = None
    providers: list[str] = []


class AuthConfigResponse(BaseModel):
    auth_enabled: bool
    providers: list[str] = []


def _provider_names() -> list[str]:
    return list(auth_settings.providers)


def _callback_url(provider: str, request: Request) -> str:
    if auth_settings.redirect_base_url:
        base = auth_settings.redirect_base_url.rstrip("/")
        return f"{base}/auth/callback/{provider}"
    return str(request.url_for("oauth_callback", provider=provider))


def _ui_redirect(*, error: str | None = None) -> str:
    url = auth_settings.ui_redirect_url
    if error:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{urlencode({'auth_error': error})}"
    return url


def _google_user(token: dict[str, Any], request: Request) -> AuthUser:
    info = token.get("userinfo")
    if not info and token.get("id_token"):
        client = oauth.create_client("google")
        info = client.parse_id_token(request, token)
    if not info:
        raise HTTPException(status_code=502, detail="Google did not return user info")
    sub = str(info.get("sub") or info.get("id") or "")
    if not sub:
        raise HTTPException(status_code=502, detail="Google user id missing")
    return AuthUser(
        id=f"google:{sub}",
        email=info.get("email"),
        name=info.get("name"),
        picture=info.get("picture"),
        provider="google",
    )


async def _github_user(token: dict[str, Any]) -> AuthUser:
    access_token = token.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="GitHub access token missing")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        profile_resp = await client.get("https://api.github.com/user", headers=headers)
        if profile_resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"GitHub profile request failed ({profile_resp.status_code})",
            )
        profile = profile_resp.json()
        email = profile.get("email")
        if not email:
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers=headers,
            )
            if emails_resp.status_code < 400:
                for row in emails_resp.json():
                    if row.get("primary") and row.get("verified"):
                        email = row.get("email")
                        break
                if not email:
                    for row in emails_resp.json():
                        if row.get("verified"):
                            email = row.get("email")
                            break
    user_id = profile.get("id")
    if user_id is None:
        raise HTTPException(status_code=502, detail="GitHub user id missing")
    return AuthUser(
        id=f"github:{user_id}",
        email=email,
        name=profile.get("name") or profile.get("login"),
        picture=profile.get("avatar_url"),
        provider="github",
    )


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    return AuthConfigResponse(
        auth_enabled=auth_settings.enabled,
        providers=_provider_names(),
    )


@router.get("/me", response_model=AuthMeResponse)
async def auth_me(request: Request) -> AuthMeResponse:
    user = optional_user(request)
    return AuthMeResponse(
        auth_enabled=auth_settings.enabled,
        authenticated=user is not None,
        user=AuthUserPublic(**user.as_public_dict()) if user else None,
        providers=_provider_names(),
    )


@router.get("/login/{provider}")
async def oauth_login(provider: str, request: Request) -> RedirectResponse:
    if not auth_settings.enabled:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
    if provider not in auth_settings.providers:
        raise HTTPException(status_code=404, detail=f"Unknown auth provider: {provider}")
    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(status_code=503, detail=f"Provider not configured: {provider}")
    redirect_uri = _callback_url(provider, request)
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/callback/{provider}", name="oauth_callback")
async def oauth_callback(provider: str, request: Request) -> RedirectResponse:
    if not auth_settings.enabled:
        raise HTTPException(status_code=404, detail="Authentication is disabled")
    if provider not in auth_settings.providers:
        raise HTTPException(status_code=404, detail=f"Unknown auth provider: {provider}")
    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(status_code=503, detail=f"Provider not configured: {provider}")
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        logger.warning("OAuth callback failed provider=%s error=%s", provider, exc)
        return RedirectResponse(
            url=_ui_redirect(error="oauth_failed"),
            status_code=302,
        )
    try:
        if provider == "google":
            user = _google_user(token, request)
        elif provider == "github":
            user = await _github_user(token)
        else:
            raise HTTPException(status_code=404, detail=f"Unknown auth provider: {provider}")
    except HTTPException:
        return RedirectResponse(
            url=_ui_redirect(error="profile_failed"),
            status_code=302,
        )
    response = RedirectResponse(url=_ui_redirect(), status_code=302)
    set_session_cookie(response, user)
    return response


@router.post("/logout")
async def auth_logout_post() -> JSONResponse:
    response = JSONResponse(content={"status": "ok"})
    clear_session_cookie(response)
    return response


@router.get("/logout")
async def auth_logout_get() -> RedirectResponse:
    response = RedirectResponse(url=_ui_redirect(), status_code=302)
    clear_session_cookie(response)
    return response
