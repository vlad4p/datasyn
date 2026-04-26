"""Single shared ``httpx.Client`` with timeout, retries-less, and a configurable UA."""

from __future__ import annotations

import os
from typing import Any

import httpx


_USER_AGENT_DEFAULT = "Datacyber-Scrapper/1.0 (+https://github.com/datacyber)"


def _timeout_seconds() -> float:
    try:
        return float(os.environ.get("HTTP_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0


def build_client(**kwargs: Any) -> httpx.Client:
    """Return a sync ``httpx.Client`` suitable for INDEC-style file downloads."""

    headers = {
        "User-Agent": os.environ.get("HTTP_USER_AGENT") or _USER_AGENT_DEFAULT,
        "Accept": "*/*",
    }
    return httpx.Client(
        timeout=_timeout_seconds(),
        follow_redirects=True,
        headers=headers,
        **kwargs,
    )


def head(client: httpx.Client, url: str) -> httpx.Response:
    return client.head(url)
