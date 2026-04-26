"""Discover INDEC EPH ``usu_*`` microdata files under ``{eph_base}/{year}/Q*``."""

from __future__ import annotations

import os
import re
from pathlib import Path

_QDIR = re.compile(r"^Q([1-4])$", re.IGNORECASE)


def eph_year_root() -> Path:
    base = Path(
        os.environ.get("INDEC_EPH_BASE", "/data-local/indec/mercado_laboral/EPH")
    ).expanduser()
    year = int(os.environ.get("INDEC_EPH_YEAR", "2025"))
    return (base / str(year)).resolve()


def quarter_num_from_key(partition_key: str) -> int:
    """``Q1`` → ``1``."""
    m = _QDIR.match(partition_key.strip())
    if not m:
        raise ValueError(f"invalid quarter partition key: {partition_key!r}")
    return int(m.group(1))


def list_quarter_dirs(year_root: Path) -> list[tuple[str, Path]]:
    """Sorted ``(Qn, path)`` for each ``Q[1-4]`` directory under *year_root*."""
    found: list[tuple[str, Path]] = []
    if not year_root.is_dir():
        return found
    for child in sorted(year_root.iterdir()):
        if child.is_dir() and _QDIR.match(child.name):
            found.append((child.name, child))
    return found


def find_usu_txt(quarter_dir: Path, *, hogar: bool) -> Path | None:
    """First ``usu_hogar_*.txt`` or ``usu_individual_*.txt`` under *quarter_dir* (recursive)."""
    pat = "usu_hogar_*.txt" if hogar else "usu_individual_*.txt"
    matches = sorted(quarter_dir.rglob(pat))
    if not matches:
        return None
    return matches[0]


def partition_keys_for_year(_year_root: Path | None = None) -> list[str]:
    """Canonical EPH quarters ``Q1``…``Q4`` (stable Dagster keys).

    Partitions are **not** trimmed to folders present at repo load time: that
    caused ``DagsterInvalidInvocationError`` (e.g. backfill ``Q3`` while the
    code location only exposed ``Q1``, ``Q2``). Missing quarter dirs are
    handled at materialization time (skip / log).

    *_year_root* is ignored; kept so callers can pass ``eph_year_root()`` for
    readability.
    """
    return ["Q1", "Q2", "Q3", "Q4"]
