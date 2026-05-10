"""Discover all submodules under a package and pick the symbol matching the
module name. Used by `definitions.py` so each new file scaffolded by
`dagster-mcp` (jobs/, schedules/, sensors/) is auto-registered with no edits
to `definitions.py`.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def collect_named(package: ModuleType) -> list:
    out: list = []
    for info in pkgutil.iter_modules(package.__path__):
        mod = importlib.import_module(f"{package.__name__}.{info.name}")
        sym = getattr(mod, info.name, None)
        if sym is None:
            continue
        out.append(sym)
    return out
