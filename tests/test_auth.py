"""Auth configuration and session token tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from agent.auth.config import AuthSettings
from agent.auth.session import AuthUser, create_session_token, decode_session_token


def test_auth_settings_auto_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "google-id")
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    cfg = AuthSettings.load()
    assert cfg.enabled is True
    assert cfg.providers == ("google",)


def test_auth_settings_explicit_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_ID", "gh-id")
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_SECRET", "gh-secret")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    cfg = AuthSettings.load()
    assert cfg.enabled is False


def test_session_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAUTH_SESSION_SECRET", "roundtrip-secret")
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "google-id")
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_SECRET", "google-secret")
    import agent.auth.config as auth_config

    auth_config.auth_settings = AuthSettings.load()
    user = AuthUser(
        id="google:123",
        email="user@example.com",
        name="Test User",
        picture="https://example.com/a.png",
        provider="google",
    )
    token = create_session_token(user)
    decoded = decode_session_token(token)
    assert decoded == user


def test_session_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAUTH_SESSION_SECRET", "expired-secret")
    import agent.auth.config as auth_config

    auth_config.auth_settings = AuthSettings.load()
    payload = {
        "sub": "github:1",
        "email": "a@b.com",
        "name": "A",
        "picture": None,
        "provider": "github",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) - timedelta(seconds=30),
    }
    token = jwt.encode(payload, "expired-secret", algorithm="HS256")
    assert decode_session_token(token) is None
