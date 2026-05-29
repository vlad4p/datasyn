"""Authlib OAuth client registration."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from agent.auth.config import auth_settings

oauth = OAuth()


def register_oauth_clients() -> None:
    if auth_settings.google_client_id and auth_settings.google_client_secret:
        oauth.register(
            name="google",
            client_id=auth_settings.google_client_id,
            client_secret=auth_settings.google_client_secret,
            server_metadata_url=(
                "https://accounts.google.com/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid email profile"},
        )
    if auth_settings.github_client_id and auth_settings.github_client_secret:
        oauth.register(
            name="github",
            client_id=auth_settings.github_client_id,
            client_secret=auth_settings.github_client_secret,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email"},
        )
