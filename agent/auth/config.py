"""OAuth and session configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

from agent.config import _env_first


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _providers_configured(
    *,
    google_client_id: str | None,
    google_client_secret: str | None,
    github_client_id: str | None,
    github_client_secret: str | None,
) -> tuple[str, ...]:
    out: list[str] = []
    if google_client_id and google_client_secret:
        out.append("google")
    if github_client_id and github_client_secret:
        out.append("github")
    return tuple(out)


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    session_secret: str | None
    session_max_age_seconds: int
    secure_cookies: bool
    redirect_base_url: str | None
    ui_redirect_url: str
    google_client_id: str | None
    google_client_secret: str | None
    github_client_id: str | None
    github_client_secret: str | None
    providers: tuple[str, ...]

    @classmethod
    def load(cls) -> AuthSettings:
        session_secret = _env_first("OAUTH_SESSION_SECRET", "AUTH_SESSION_SECRET")
        google_client_id = _env_first("OAUTH_GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_ID")
        google_client_secret = _env_first(
            "OAUTH_GOOGLE_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        )
        github_client_id = _env_first("OAUTH_GITHUB_CLIENT_ID", "GITHUB_CLIENT_ID")
        github_client_secret = _env_first(
            "OAUTH_GITHUB_CLIENT_SECRET",
            "GITHUB_CLIENT_SECRET",
        )
        providers = _providers_configured(
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            github_client_id=github_client_id,
            github_client_secret=github_client_secret,
        )
        explicit = os.environ.get("AUTH_ENABLED")
        if explicit is not None and str(explicit).strip():
            enabled = _truthy("AUTH_ENABLED")
        else:
            enabled = bool(session_secret and providers)
        redirect_base = _env_first("OAUTH_REDIRECT_BASE_URL", "AUTH_REDIRECT_BASE_URL")
        ui_redirect = (
            _env_first("OAUTH_UI_REDIRECT_URL", "AUTH_UI_REDIRECT_URL") or "/"
        ).strip()
        if not ui_redirect.startswith("/"):
            ui_redirect = f"/{ui_redirect}"
        return cls(
            enabled=enabled,
            session_secret=session_secret,
            session_max_age_seconds=int(
                os.environ.get("OAUTH_SESSION_MAX_AGE_SECONDS", "604800")
            ),
            secure_cookies=_truthy("OAUTH_SECURE_COOKIES"),
            redirect_base_url=redirect_base.rstrip("/") if redirect_base else None,
            ui_redirect_url=ui_redirect,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            github_client_id=github_client_id,
            github_client_secret=github_client_secret,
            providers=providers,
        )


auth_settings = AuthSettings.load()
