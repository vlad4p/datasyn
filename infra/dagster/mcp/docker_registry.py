"""Optional Docker registry prefix for code-location image builds.

When ``DOCKER_REGISTRY`` is set (e.g. ``localhost:5000/datasyn``), ``build_image`` also tags
``<registry>/<local-image-ref>`` so ``docker push`` can publish without changing the short local name
(``dagster_user_code_image:latest``). The root ``Makefile`` exports ``DOCKER_REGISTRY`` from
``DATASYN_IMAGE_REGISTRY`` / ``DATASYN_IMAGE_NAMESPACE`` so compose and MCP stay aligned.
"""

from __future__ import annotations

import os


def docker_registry_prefix() -> str | None:
    """Return registry host/path with no trailing slash, or ``None`` for local-only names."""
    raw = (os.environ.get("DOCKER_REGISTRY") or "").strip().rstrip("/")
    if not raw:
        return None
    return raw


def looks_like_remote_image_ref(image_ref: str) -> bool:
    """Heuristic: *image_ref* already names a registry (skip mirror tag)."""
    ref = image_ref.strip()
    if not ref:
        return False
    repo = ref.split(":")[0]
    if "/" not in repo:
        return False
    head = repo.split("/", 1)[0]
    if head == "localhost" or ":" in head:
        return True
    if "." in head:
        return True
    return False


def registry_mirror_tags(local_image_ref: str) -> list[str]:
    """Return extra ``docker build -t`` tags under ``DOCKER_REGISTRY``, if configured."""
    reg = docker_registry_prefix()
    if not reg:
        return []
    ref = local_image_ref.strip()
    if not ref:
        return []
    if ref.startswith(reg + "/"):
        return []
    if looks_like_remote_image_ref(ref):
        return []
    return [f"{reg}/{ref}"]
