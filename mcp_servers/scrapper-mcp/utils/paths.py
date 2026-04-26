"""Filesystem helpers confined to ``DATA_LOCAL_ROOT``.

Downloads must stay inside the mounted data directory so the warehouse (duckdb-mcp)
can read them and we never leak writes outside the container mount.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


def data_local_root() -> Path:
    return Path(os.environ.get("DATA_LOCAL_ROOT", "/data-local")).resolve()


def safe_segment(value: str, *, fallback: str = "unnamed") -> str:
    """Return a filesystem-safe single path segment (no separators, no traversal)."""

    cleaned = _SAFE_SEGMENT.sub("_", (value or "").strip())
    cleaned = cleaned.strip("._") or fallback
    return cleaned[:80]


def resolve_under_root(root: Path, *parts: str) -> Path:
    """Join ``parts`` under ``root`` and ensure the resolved path stays under it."""

    safe = [safe_segment(p) for p in parts if p is not None and str(p) != ""]
    candidate = (root.joinpath(*safe)).resolve() if safe else root.resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"refusing path outside data root: {candidate} (root={root_resolved})"
        ) from exc
    return candidate
