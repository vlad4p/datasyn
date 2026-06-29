"""Load MCP HTTP endpoints from ``mcp.json`` with host-friendly URL rewriting.

When the brain runs on the **host** (``make agent-dev``), Docker-internal MCP hostnames
(``duckdb-mcp``, ``storage-mcp``) are rewritten to ``127.0.0.1:<port>``.

When the brain runs **inside Docker**, loopback URLs (``127.0.0.1`` / ``localhost``) are
rewritten to ``host.docker.internal`` so the container can reach MCP servers on the host.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from agent.utils.litellm_chat import running_in_docker

logger = logging.getLogger(__name__)

# Hostnames from ``mcp.json`` that only resolve inside a platform Docker network.
_DOCKER_ONLY_MCP_HOSTS = frozenset(
    {
        "duckdb-mcp",
        "storage-mcp",
    }
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _rewrite_mcp_url_for_host_process(url: str) -> str:
    """If URL targets a Docker-internal MCP hostname, use loopback with the same port."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _DOCKER_ONLY_MCP_HOSTS:
        return url
    port = parsed.port
    if port is None:
        logger.warning(
            "MCP URL %r has no port; cannot rewrite for host access; leaving unchanged",
            url,
        )
        return url
    loopback = urlunparse(
        (
            parsed.scheme or "http",
            f"127.0.0.1:{port}",
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return loopback


def _rewrite_mcp_url_for_docker(url: str) -> str:
    """Inside Docker, loopback is the container — reach MCP on the host instead."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return url
    port = parsed.port
    if port is None:
        logger.warning(
            "MCP URL %r has no port; cannot rewrite for Docker host access; leaving unchanged",
            url,
        )
        return url
    gateway = urlunparse(
        (
            parsed.scheme or "http",
            f"host.docker.internal:{port}",
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return gateway


def load_mcp_tool_connections(project_root: Path | None = None) -> dict[str, Any]:
    """Build the LangChain MCP client ``connections`` map (transport + url per server key).

    * On the **host**: rewrite Docker-only hostnames to ``127.0.0.1``.
    * **Inside** the brain container: rewrite loopback to ``host.docker.internal``.

    Set ``MCP_DISABLE_HOST_URL_REWRITE=1`` to always use raw ``mcp.json`` URLs.
    """
    root = project_root
    if root is None:
        from agent.config import settings

        root = settings.project_root

    cfg_path = root / "mcp.json"
    override = (os.environ.get("MCP_JSON_PATH") or "").strip()
    if override:
        cfg_path = Path(override).expanduser().resolve()

    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"Missing {cfg_path}: define MCP HTTP servers there (see project mcp.json)."
        )
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    block = raw.get("mcpServers") or raw.get("servers")
    if not isinstance(block, dict) or not block:
        raise ValueError(
            "mcp.json must contain a non-empty object under 'mcpServers' or 'servers'."
        )
    connections: dict[str, Any] = {}
    for name, spec in block.items():
        if not isinstance(spec, dict):
            continue
        url = spec.get("url")
        if not url:
            continue
        transport = spec.get("transport") or "http"
        url_str = str(url)
        effective = url_str
        disable_rewrite = os.environ.get("MCP_DISABLE_HOST_URL_REWRITE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not disable_rewrite:
            if running_in_docker():
                effective = _rewrite_mcp_url_for_docker(url_str)
                if effective != url_str:
                    logger.info(
                        "MCP URL rewrite (Docker): %s -> %s",
                        url_str,
                        effective,
                    )
            else:
                effective = _rewrite_mcp_url_for_host_process(url_str)
                if effective != url_str:
                    logger.info(
                        "MCP URL rewrite (host process): %s -> %s",
                        url_str,
                        effective,
                    )
        connections[str(name)] = {"transport": transport, "url": effective}
    if not connections:
        raise ValueError("mcp.json: no entries with a 'url' field.")
    return connections
