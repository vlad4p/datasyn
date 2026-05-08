"""Project / asset / job / schedule / sensor scaffolding for the Dagster MCP.

Pure file-system operations: every function returns a manifest dict and never
shells out. Templates live in ``./templates/*.tpl``; placeholders are filled
via ``str.format`` so the scaffolds remain dependency-free.

Idempotency contract: ``create_project`` errors if the target already exists
(unless ``overwrite=True``); the per-entity ``add_*`` helpers refuse to
overwrite an existing file unless asked, so the agent can always ``add_*``
again to learn the existing path without clobbering.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_ENTITY_KINDS: tuple[str, ...] = ("assets", "jobs", "schedules", "sensors")


def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _read_template(name: str) -> str:
    return (_templates_dir() / name).read_text(encoding="utf-8")


def _validate_python_name(name: str, *, what: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid {what} name {name!r}: must match {_NAME_RE.pattern} "
            "(lowercase, start with a letter, ≤63 chars, only [a-z0-9_])"
        )


def _projects_root(root: str | Path) -> Path:
    p = Path(root).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _project_dir(root: str | Path, project: str) -> Path:
    _validate_python_name(project, what="project")
    return _projects_root(root) / project


def _resolve_project_dir(root: str | Path, project: str) -> Path:
    """Resolve project input as either name or path under projects root."""
    base = _projects_root(root)
    raw = (project or "").strip()
    if not raw:
        raise ValueError("project is required")

    # Accept plain project names (recommended).
    if "/" not in raw and "\\" not in raw:
        _validate_python_name(raw, what="project")
        return base / raw

    # Also accept path-like values to make tool usage robust.
    p = Path(raw)
    candidate = (base / p).resolve() if not p.is_absolute() else p.resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(
            f"project path {raw!r} must be inside {base}"
        ) from exc
    _validate_python_name(candidate.name, what="project")
    return candidate


def _project_pkg(root: str | Path, project: str) -> Path:
    pdir = _ensure_project(root, project)
    pkg = _package_root(pdir)
    if pkg is None:
        raise FileNotFoundError(
            f"project package not found under {pdir}; expected either "
            f"{pdir / pdir.name} or {pdir / 'src' / pdir.name}"
        )
    return pkg


def _package_root(project_dir: Path) -> Path | None:
    """``<project>/<name>/`` (flat) or ``<project>/src/<name>/`` (src layout)."""
    name = project_dir.name
    src_pkg = project_dir / "src" / name
    if (src_pkg / "__init__.py").is_file():
        return src_pkg
    flat = project_dir / name
    if (flat / "__init__.py").is_file():
        return flat
    return None


def _ensure_project(root: str | Path, project: str) -> Path:
    pdir = _resolve_project_dir(root, project)
    if _package_root(pdir) is None:
        raise FileNotFoundError(
            f"project {project!r} not found at {pdir}; run create_project first"
        )
    return pdir


def _python_lit(s: str) -> str:
    """Render *s* as a Python string literal safe for f-string substitution."""
    return repr(s)


def _write(path: Path, contents: str, *, overwrite: bool = False) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return {"path": str(path), "written": False, "reason": "exists"}
    path.write_text(contents, encoding="utf-8")
    return {"path": str(path), "written": True}


def list_projects(root: str | Path) -> dict[str, Any]:
    """List every directory under *root* that looks like a Dagster project.

    Does not create *root* (unlike ``_projects_root``): listing must never call
    ``mkdir`` on e.g. ``/projects`` on the host, which macOS denies.
    """
    base = Path(root).resolve()
    if not base.exists():
        return {
            "root": str(base),
            "projects": [],
            "note": "projects root does not exist; set DAGSTER_PROJECTS_ROOT or create/mount it",
        }
    if not base.is_dir():
        raise ValueError(f"projects root is not a directory: {base}")
    entries = []
    try:
        children = sorted(base.iterdir())
    except PermissionError as exc:
        return {
            "root": str(base),
            "projects": [],
            "note": f"permission denied listing projects root ({exc})",
        }
    for child in children:
        if not child.is_dir():
            continue
        if _package_root(child) is None:
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "has_dockerfile": (child / "Dockerfile").is_file(),
                "has_workspace": (child / "workspace.yaml").is_file(),
                "counts": _entity_counts(child),
            }
        )
    return {"root": str(base), "projects": entries}


def _entity_counts(project_dir: Path) -> dict[str, int]:
    pkg = _package_root(project_dir)
    counts: dict[str, int] = {}
    if pkg is None:
        return {k: 0 for k in _ENTITY_KINDS}
    for kind in _ENTITY_KINDS:
        sub = pkg / kind
        if not sub.is_dir():
            counts[kind] = 0
            continue
        counts[kind] = sum(
            1
            for p in sub.iterdir()
            if p.is_file() and p.suffix == ".py" and p.name != "__init__.py"
        )
    return counts


def create_project(
    root: str | Path,
    name: str,
    *,
    description: str = "",
    webserver_port: int = 3000,
    overwrite: bool = False,
) -> dict[str, Any]:
    _validate_python_name(name, what="project")
    pdir = _project_dir(root, name)
    if pdir.exists() and any(pdir.iterdir()) and not overwrite:
        raise FileExistsError(f"project directory already exists: {pdir}")
    pkg = pdir / name
    written: list[dict[str, Any]] = []

    written.append(
        _write(
            pdir / "pyproject.toml",
            _read_template("pyproject.toml.tpl").format(
                name=name, description=description
            ),
            overwrite=overwrite,
        )
    )
    written.append(
        _write(
            pdir / "workspace.yaml",
            _read_template("workspace.yaml.tpl").format(name=name),
            overwrite=overwrite,
        )
    )
    written.append(
        _write(
            pdir / "Dockerfile",
            _read_template("Dockerfile.tpl").format(
                name=name, port=webserver_port
            ),
            overwrite=overwrite,
        )
    )
    written.append(
        _write(
            pdir / ".dockerignore",
            _read_template("dockerignore.tpl"),
            overwrite=overwrite,
        )
    )
    written.append(
        _write(
            pdir / "README.md",
            _read_template("README.md.tpl").format(
                name=name, description=description or f"Dagster project '{name}'."
            ),
            overwrite=overwrite,
        )
    )

    written.append(
        _write(
            pkg / "__init__.py",
            _read_template("pkg__init__.py.tpl").format(name=name),
            overwrite=overwrite,
        )
    )
    written.append(
        _write(
            pkg / "definitions.py",
            _read_template("definitions.py.tpl"),
            overwrite=overwrite,
        )
    )
    written.append(
        _write(
            pkg / "_collect.py",
            _read_template("_collect.py.tpl"),
            overwrite=overwrite,
        )
    )

    for kind in _ENTITY_KINDS:
        written.append(
            _write(
                pkg / kind / "__init__.py",
                _read_template("subpkg__init__.py.tpl").format(
                    kind=kind.capitalize(), name=name
                ),
                overwrite=overwrite,
            )
        )

    example_asset = _read_template("asset.py.tpl").format(
        name="example",
        description="Example asset — verifies the project loads.",
        group="example",
    )
    written.append(
        _write(pkg / "assets" / "example.py", example_asset, overwrite=overwrite)
    )

    example_job = _read_template("job.py.tpl").format(
        name="example_job",
        selection_expr='all()',
        description="Materialize every asset in the project.",
        description_lit=_python_lit("Materialize every asset in the project."),
    )
    written.append(
        _write(pkg / "jobs" / "example_job.py", example_job, overwrite=overwrite)
    )

    return {
        "name": name,
        "path": str(pdir),
        "package": str(pkg),
        "files": written,
        "next_steps": [
            f"dagster_add_asset    project={name!r} name='my_asset'",
            f"dagster_add_job      project={name!r} name='my_job' selection='*'",
            f"dagster_deploy       project={name!r} host_port=3001",
        ],
    }


def add_asset(
    root: str | Path,
    project: str,
    name: str,
    *,
    description: str = "",
    group: str = "default",
    overwrite: bool = False,
) -> dict[str, Any]:
    _ensure_project(root, project)
    _validate_python_name(name, what="asset")
    _validate_python_name(group, what="group")
    pkg = _project_pkg(root, project)
    target = pkg / "assets" / f"{name}.py"
    body = _read_template("asset.py.tpl").format(
        name=name,
        description=description or f"Asset {name!r} (scaffolded by dagster-mcp).",
        group=group,
    )
    return _write(target, body, overwrite=overwrite)


def _selection_expr(selection: str) -> str:
    """Render the `AssetSelection.<expr>` argument used by the job template."""
    selection = (selection or "*").strip()
    if selection == "*":
        return "all()"
    keys = [s.strip() for s in selection.split(",") if s.strip()]
    if not keys:
        return "all()"
    quoted = ", ".join(repr(k) for k in keys)
    return f"keys({quoted})"


def add_job(
    root: str | Path,
    project: str,
    name: str,
    *,
    selection: str = "*",
    description: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    _ensure_project(root, project)
    _validate_python_name(name, what="job")
    pkg = _project_pkg(root, project)
    target = pkg / "jobs" / f"{name}.py"
    desc = description or f"Job {name!r} (scaffolded by dagster-mcp)."
    body = _read_template("job.py.tpl").format(
        name=name,
        selection_expr=_selection_expr(selection),
        description=desc,
        description_lit=_python_lit(desc),
    )
    return _write(target, body, overwrite=overwrite)


def add_schedule(
    root: str | Path,
    project: str,
    name: str,
    *,
    job: str,
    cron: str = "0 9 * * *",
    description: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    _ensure_project(root, project)
    _validate_python_name(name, what="schedule")
    _validate_python_name(job, what="job")
    pkg = _project_pkg(root, project)
    if not (pkg / "jobs" / f"{job}.py").is_file():
        raise FileNotFoundError(
            f"job {job!r} not found at {pkg / 'jobs' / f'{job}.py'}; "
            "scaffold it first with dagster_add_job"
        )
    target = pkg / "schedules" / f"{name}.py"
    desc = description or f"Schedule {name!r} → job {job!r}."
    body = _read_template("schedule.py.tpl").format(
        name=name,
        job=job,
        cron=cron,
        description=desc,
        description_lit=_python_lit(desc),
    )
    return _write(target, body, overwrite=overwrite)


def add_sensor(
    root: str | Path,
    project: str,
    name: str,
    *,
    job: str,
    minimum_interval_seconds: int = 30,
    description: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    _ensure_project(root, project)
    _validate_python_name(name, what="sensor")
    _validate_python_name(job, what="job")
    pkg = _project_pkg(root, project)
    if not (pkg / "jobs" / f"{job}.py").is_file():
        raise FileNotFoundError(
            f"job {job!r} not found at {pkg / 'jobs' / f'{job}.py'}; "
            "scaffold it first with dagster_add_job"
        )
    target = pkg / "sensors" / f"{name}.py"
    desc = description or f"Sensor {name!r} → job {job!r}."
    body = _read_template("sensor.py.tpl").format(
        name=name,
        job=job,
        minimum_interval_seconds=int(minimum_interval_seconds),
        description=desc,
        description_lit=_python_lit(desc),
    )
    return _write(target, body, overwrite=overwrite)
