"""Dagster MCP (FastMCP HTTP): AI-assisted development for Dagster code locations under
``dagster-code/projects/`` — scaffold projects, add assets/jobs, build images (optional
registry mirror + push), drive Compose / host Docker, plus optional metadata catalog SQL.

Tools (LangChain prefixes them with the MCP key ``dagster``):

**Dagster / Docker**

- ``dagster_list_projects``   — list projects under ``DAGSTER_PROJECTS_ROOT``.
- ``dagster_create_project``  — generate a new Dagster project (pyproject, Dockerfile,
                                 workspace, package layout, an example asset + job).
- ``dagster_add_asset``       — add a file-per-asset (auto-discovered).
- ``dagster_add_job``         — add a file-per-job using ``define_asset_job``.
- ``dagster_add_schedule``    — add a ``ScheduleDefinition`` linked to a job.
- ``dagster_add_sensor``      — add a ``@sensor`` linked to a job.
- ``dagster_build_image``     — ``docker build`` the project image (primary tag + optional
                                 ``DOCKER_REGISTRY`` mirror tags; optional push if
                                 ``DOCKER_PUSH_AFTER_BUILD``).
- ``dagster_push_image``      — ``docker push`` a fully qualified image ref.
- ``dagster_compose_force_recreate`` — ``docker compose up -d --no-build --force-recreate``
                                 for an external stack (default: ``dagster_user_code``).
- ``dagster_user_code_refresh`` — build default project → ``dagster_user_code_image`` then
                                 force-recreate ``dagster_user_code``.
- ``dagster_deploy``          — ``docker build`` then ``docker rm -f`` + ``docker run``.
- ``dagster_stop`` / ``dagster_remove`` / ``dagster_logs`` / ``dagster_status``
- ``dagster_daemon_info`` — confirm host Docker daemon socket.

**Metadata catalog (PostgreSQL)**

- ``dagster_catalog_get_schema`` / ``dagster_catalog_execute_query`` — see ``./skills/catalog-sql``.

The MCP **does not** embed the Dagster runtime: it generates code and shells
out to the host Docker daemon (via mounted ``/var/run/docker.sock``).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

import scaffold
import docker_ops
import docker_registry
from catalog_db import catalog_connect
from catalog_schema_inspect import fetch_public_schema
from catalog_sql_guard import validate_catalog_sql

_env = Path(__file__).resolve().parent / ".env"
if _env.is_file():
    load_dotenv(_env)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [dagster-mcp] %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("dagster-mcp")

_DEFAULT_PROJECTS_ROOT = Path(__file__).resolve().parent / "dagster-code" / "projects"


def _resolved_projects_root() -> Path:
    """Effective ``DAGSTER_PROJECTS_ROOT``.

    Dev ``.env`` files often mirror Compose (``DAGSTER_PROJECTS_ROOT=/projects``). Inside
    the MCP container that path is bind-mounted; on the host it is missing or raises
    ``PermissionError`` on macOS. Fall back to ``…/mcp/dagster-code/projects`` when ``/projects``
    is not a readable directory.
    """
    default = _DEFAULT_PROJECTS_ROOT.resolve()
    raw = (os.environ.get("DAGSTER_PROJECTS_ROOT") or "").strip()
    if not raw:
        return default
    candidate = Path(raw).expanduser().resolve()
    if candidate != Path("/projects"):
        return candidate
    try:
        if candidate.is_dir():
            os.listdir(candidate)
            return candidate
    except OSError as exc:
        log.warning(
            "DAGSTER_PROJECTS_ROOT=/projects not usable (%s); using %s",
            exc,
            default,
        )
        return default
    log.warning(
        "DAGSTER_PROJECTS_ROOT=/projects not present here; using %s",
        default,
    )
    return default


HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8043"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")

PROJECTS_ROOT = _resolved_projects_root()
PROJECT_NETWORK = os.environ.get("DAGSTER_PROJECT_NETWORK", "infra-datasynk")
IMAGE_PREFIX = os.environ.get("DAGSTER_IMAGE_PREFIX", "dagster").rstrip("/")
CONTAINER_PREFIX = os.environ.get("DAGSTER_CONTAINER_PREFIX", "dagster").rstrip("-")
DEFAULT_HOST_PORT = int(os.environ.get("DAGSTER_DEFAULT_HOST_PORT", "3001"))
WEBSERVER_PORT = int(os.environ.get("DAGSTER_WEBSERVER_PORT", "3000"))
# Semicolon-separated `src:dst[:mode]` mounts passed to `docker run -v` for
# `dagster_deploy` (paths are resolved on the **host** by the Docker daemon).
# Example (host shell before `compose up`):
#   export DAGSTER_DEPLOY_VOLUMES="duckdb_data:/data;storage:/storage;/abs/path/datacyber/data-local:/data-local:ro"
DAGSTER_DEPLOY_VOLUMES = os.environ.get(
    "DAGSTER_DEPLOY_VOLUMES",
    "duckdb_data:/data;storage:/storage",
)
DAGSTER_COMPOSE_FILE = (os.environ.get("DAGSTER_COMPOSE_FILE") or "").strip()
DAGSTER_COMPOSE_USER_CODE_SERVICE = os.environ.get(
    "DAGSTER_COMPOSE_USER_CODE_SERVICE",
    "dagster_user_code",
).strip()
DAGSTER_COMPOSE_PROJECT = (os.environ.get("DAGSTER_COMPOSE_PROJECT") or "").strip()
# Defaults match ``infra/dagster/docker-compose.yaml`` (``dagster_user_code`` image).
DAGSTER_USER_CODE_BUILD_PROJECT = (
    os.environ.get("DAGSTER_USER_CODE_BUILD_PROJECT") or "datasyn"
).strip()
DAGSTER_USER_CODE_IMAGE_NAME = (
    os.environ.get("DAGSTER_USER_CODE_IMAGE_NAME") or "dagster_user_code_image"
).strip()

LIST_CAP_CATALOG = max(1, min(int(os.environ.get("CATALOG_LIST_CAP", "100")), 500))

mcp = FastMCP(
    name="dagster-mcp",
    instructions=(
        "Datacyber Dagster MCP — AI-assisted development for code locations under "
        "`/projects/<name>/` (repo: `infra/dagster/mcp/dagster-code/projects/`, bind-mounted). "
        "Use bounded tools: `create_project`, `add_asset`, `add_job`, `add_schedule`, `add_sensor`, "
        "`build_image` (optional `DOCKER_REGISTRY` mirror tags + `DOCKER_PUSH_AFTER_BUILD`), "
        "`push_image`, `user_code_refresh` (rebuild `datasyn` → `dagster_user_code_image` + compose recreate), "
        "`compose_force_recreate`, `deploy`, catalog SQL. "
        "Never invent paths: list projects first. The MCP does not import Dagster; it writes files "
        "and shells out to `docker` on the host socket. Set `DATABASE_URL` / `CATALOG_DATABASE_URL` "
        "for catalog tools."
    ),
)


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _err(exc: BaseException, **extra: Any) -> str:
    return _json({"ok": False, "error": f"{type(exc).__name__}: {exc}", **extra})


def _image_for(project: str, tag: str | None) -> str:
    base = f"{IMAGE_PREFIX}/{project}"
    return f"{base}:{tag or 'latest'}"


def _full_image_ref(
    project: str,
    *,
    tag: str | None,
    image_name: str | None,
) -> str:
    """Resolve the Docker image ref for build/deploy/remove.

    If *image_name* is set, it is the full repository name (optionally with
    ``:tag``). Without a colon, *tag* (or ``latest``) is appended — e.g.
    ``dagster_user_code_image`` → ``dagster_user_code_image:latest``.
    Otherwise use ``<DAGSTER_IMAGE_PREFIX>/<project>:<tag>``.
    """
    if image_name and image_name.strip():
        ref = image_name.strip()
        if ":" in ref:
            return ref
        return f"{ref}:{tag or 'latest'}"
    return _image_for(project, tag)


def _container_for(project: str) -> str:
    return f"{CONTAINER_PREFIX}-{project}"


def _push_after_build_enabled() -> bool:
    return os.environ.get("DOCKER_PUSH_AFTER_BUILD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _build_project_image(
    *,
    context_dir: Path,
    primary_tag: str,
    no_cache: bool = False,
    pull: bool = False,
) -> dict[str, Any]:
    """``docker build`` with optional ``DOCKER_REGISTRY`` extra tags and push."""
    mirrors = docker_registry.registry_mirror_tags(primary_tag)
    build_result = docker_ops.build_image(
        context_dir=context_dir,
        tag=primary_tag,
        no_cache=no_cache,
        pull=pull,
        extra_tags=mirrors,
    )
    out: dict[str, Any] = {
        "build": build_result,
        "primary_tag": primary_tag,
        "registry_mirror_tags": mirrors,
        "docker_registry": os.environ.get("DOCKER_REGISTRY") or "",
    }
    pushes: list[dict[str, Any]] = []
    if _push_after_build_enabled() and mirrors:
        for m in mirrors:
            pushes.append(docker_ops.push_image(m))
    if pushes:
        out["push"] = pushes
    return out


@mcp.tool()
def list_projects() -> str:
    """List every scaffolded Dagster project under ``DAGSTER_PROJECTS_ROOT``."""
    log.info("tool list_projects root=%s", PROJECTS_ROOT)
    try:
        return _json(scaffold.list_projects(PROJECTS_ROOT))
    except Exception as exc:
        log.exception("list_projects failed")
        return _err(exc)


@mcp.tool()
def create_project(
    name: str,
    description: str = "",
    overwrite: bool = False,
) -> str:
    """Scaffold a new Dagster project at ``/projects/<name>/``.

    The project ships with: ``pyproject.toml``, ``workspace.yaml``, ``Dockerfile``,
    a ``<name>`` Python package with ``definitions.py`` (auto-collects every
    submodule under ``assets/`` / ``jobs/`` / ``schedules/`` / ``sensors/``), an
    example asset and an example job. Run ``dagster_deploy`` to build the image and
    replace the project container (or ``dagster_build_image`` only if you skip deploy).
    """
    log.info("tool create_project name=%r description=%r overwrite=%s", name, description, overwrite)
    t0 = time.perf_counter()
    try:
        out = scaffold.create_project(
            PROJECTS_ROOT,
            name,
            description=description,
            webserver_port=WEBSERVER_PORT,
            overwrite=overwrite,
        )
        log.info("create_project ok files=%s ms=%.2f", len(out["files"]), (time.perf_counter() - t0) * 1000)
        return _json(out)
    except Exception as exc:
        log.exception("create_project failed")
        return _err(exc, name=name)


@mcp.tool()
def add_asset(
    project: str,
    name: str,
    description: str = "",
    group: str = "default",
    overwrite: bool = False,
) -> str:
    """Add a Dagster ``@asset`` as ``/projects/<project>/<project>/assets/<name>.py``."""
    log.info("tool add_asset project=%r name=%r group=%r overwrite=%s", project, name, group, overwrite)
    try:
        return _json(
            scaffold.add_asset(
                PROJECTS_ROOT,
                project,
                name,
                description=description,
                group=group,
                overwrite=overwrite,
            )
        )
    except Exception as exc:
        log.exception("add_asset failed")
        return _err(exc, project=project, name=name)


@mcp.tool()
def add_job(
    project: str,
    name: str,
    selection: str = "*",
    description: str = "",
    overwrite: bool = False,
) -> str:
    """Add a Dagster ``define_asset_job`` (selection ``"*"`` or comma-separated keys)."""
    log.info("tool add_job project=%r name=%r selection=%r overwrite=%s", project, name, selection, overwrite)
    try:
        return _json(
            scaffold.add_job(
                PROJECTS_ROOT,
                project,
                name,
                selection=selection,
                description=description,
                overwrite=overwrite,
            )
        )
    except Exception as exc:
        log.exception("add_job failed")
        return _err(exc, project=project, name=name)


@mcp.tool()
def add_schedule(
    project: str,
    name: str,
    job: str,
    cron: str = "0 9 * * *",
    description: str = "",
    overwrite: bool = False,
) -> str:
    """Add a ``ScheduleDefinition`` bound to an existing job."""
    log.info("tool add_schedule project=%r name=%r job=%r cron=%r", project, name, job, cron)
    try:
        return _json(
            scaffold.add_schedule(
                PROJECTS_ROOT,
                project,
                name,
                job=job,
                cron=cron,
                description=description,
                overwrite=overwrite,
            )
        )
    except Exception as exc:
        log.exception("add_schedule failed")
        return _err(exc, project=project, name=name)


@mcp.tool()
def add_sensor(
    project: str,
    name: str,
    job: str,
    minimum_interval_seconds: int = 30,
    description: str = "",
    overwrite: bool = False,
) -> str:
    """Add a ``@sensor`` bound to an existing job (default body emits ``SkipReason``)."""
    log.info("tool add_sensor project=%r name=%r job=%r interval=%s", project, name, job, minimum_interval_seconds)
    try:
        return _json(
            scaffold.add_sensor(
                PROJECTS_ROOT,
                project,
                name,
                job=job,
                minimum_interval_seconds=minimum_interval_seconds,
                description=description,
                overwrite=overwrite,
            )
        )
    except Exception as exc:
        log.exception("add_sensor failed")
        return _err(exc, project=project, name=name)


@mcp.tool()
def build_image(
    project: str,
    tag: str | None = None,
    image_name: str | None = None,
    no_cache: bool = False,
    pull: bool = False,
) -> str:
    """``docker build`` the project image.

    Default tag: ``<DAGSTER_IMAGE_PREFIX>/<project>:<tag|latest>``.

    Set *image_name* to a fixed repository name (Dagster “user code image”
    convention), e.g. ``dagster_user_code_image`` → ``dagster_user_code_image:latest``,
    or pass ``dagster_user_code_image:1.0`` to include the tag in *image_name*.

    If ``DOCKER_REGISTRY`` is set, also tags ``<registry>/<same-image>`` (Compose still
    uses the primary local name). When ``DOCKER_PUSH_AFTER_BUILD`` is truthy, pushes
    those mirror tags after a successful build.
    """
    log.info(
        "tool build_image project=%r tag=%r image_name=%r no_cache=%s pull=%s",
        project,
        tag,
        image_name,
        no_cache,
        pull,
    )
    t0 = time.perf_counter()
    try:
        scaffold._ensure_project(PROJECTS_ROOT, project)  # noqa: SLF001
        image = _full_image_ref(project, tag=tag, image_name=image_name)
        ctx = PROJECTS_ROOT / project
        result = _build_project_image(
            context_dir=ctx,
            primary_tag=image,
            no_cache=no_cache,
            pull=pull,
        )
        log.info("build_image ok image=%s ms=%.2f", image, (time.perf_counter() - t0) * 1000)
        return _json({"ok": True, "image": image, "context": str(ctx), **result})
    except Exception as exc:
        log.exception("build_image failed")
        return _err(exc, project=project)


@mcp.tool()
def push_image(image: str) -> str:
    """``docker push`` a fully qualified image reference (e.g. registry mirror from ``build_image``)."""
    log.info("tool push_image image=%r", image)
    try:
        out = docker_ops.push_image(image.strip())
        return _json({"ok": True, "image": image.strip(), **out})
    except Exception as exc:
        log.exception("push_image failed")
        return _err(exc, image=image)


@mcp.tool()
def deploy(
    project: str,
    host_port: int = 0,
    container_port: int = 0,
    tag: str | None = None,
    image_name: str | None = None,
    rebuild: bool = True,
    no_cache: bool = False,
) -> str:
    """Build the project image (default) and run/replace the project container.

    - ``host_port=0`` (default) → use ``DAGSTER_DEFAULT_HOST_PORT``.
    - ``container_port=0`` (default) → use ``DAGSTER_WEBSERVER_PORT`` (e.g. ``3000``
      for ``dagster dev``). Set to ``4000`` when the image runs ``dagster api grpc``
      on that port (typical code-location image running ``dagster api grpc``).
    - ``rebuild=True`` (default) runs ``docker build`` on the project context first,
      then ``docker rm -f`` + ``docker run`` for ``<prefix>-<project>`` (same image
      ref as ``dagster_build_image``). Set ``rebuild=False`` to only restart the
      container against an image you already built.
    - ``image_name`` — optional fixed image ref; see ``dagster_build_image``.
    - The container is attached to the ``infra-datasynk`` network so it can reach
      ``duckdb-mcp:8040`` / ``storage-mcp:8044`` / etc., and publishes
      ``host_port:container_port``.

    Idempotent: any existing container with the same name is removed before ``run``.
    """
    chosen_port = int(host_port) or DEFAULT_HOST_PORT
    chosen_container_port = int(container_port) or WEBSERVER_PORT
    log.info(
        "tool deploy project=%r host_port=%s container_port=%s tag=%r image_name=%r rebuild=%s",
        project,
        chosen_port,
        chosen_container_port,
        tag,
        image_name,
        rebuild,
    )
    t0 = time.perf_counter()
    try:
        scaffold._ensure_project(PROJECTS_ROOT, project)  # noqa: SLF001
        image = _full_image_ref(project, tag=tag, image_name=image_name)
        steps: list[dict[str, Any]] = []
        if rebuild:
            steps.append(
                {
                    "step": "build_image",
                    "result": _build_project_image(
                        context_dir=PROJECTS_ROOT / project,
                        primary_tag=image,
                        no_cache=no_cache,
                    ),
                }
            )
        container = _container_for(project)
        vols = [v.strip() for v in DAGSTER_DEPLOY_VOLUMES.split(";") if v.strip()]
        extra_env: dict[str, str] = {
            "DUCKDB_PATH": os.environ.get("DAGSTER_DUCKDB_PATH", "/data/warehouse.duckdb"),
        }
        for key in ("CATALOG_DATABASE_URL", "INDEC_EPH_BASE"):
            val = os.environ.get(key)
            if val:
                extra_env[key] = val
        run_result = docker_ops.run_dagster_container(
            name=container,
            image=image,
            network=PROJECT_NETWORK,
            host_port=chosen_port,
            container_port=chosen_container_port,
            project=project,
            extra_env=extra_env,
            volumes=vols,
        )
        steps.append({"step": "run", "result": run_result})
        log.info(
            "deploy ok container=%s host_port=%s ms=%.2f",
            container,
            chosen_port,
            (time.perf_counter() - t0) * 1000,
        )
        return _json(
            {
                "ok": True,
                "project": project,
                "image": image,
                "container": container,
                "network": PROJECT_NETWORK,
                "host_port": chosen_port,
                "container_port": chosen_container_port,
                "ui_url_hint": f"http://127.0.0.1:{chosen_port}",
                "steps": steps,
            }
        )
    except Exception as exc:
        log.exception("deploy failed")
        return _err(exc, project=project)


@mcp.tool()
def compose_force_recreate(
    compose_file: str | None = None,
    compose_project: str | None = None,
    service: str | None = None,
    services: list[str] | None = None,
    with_build: bool = False,
) -> str:
    """Recreate Compose service(s) so containers pick up new images or mounted files.

    Runs ``docker compose -f <file> up -d [--no-build|--build] --force-recreate <svc…>``
    with *cwd* set to the compose file's directory (host daemon via socket).

    Pass ``services`` (non-empty) to recreate several at once, e.g. ``dagster_user_code`` plus
    webserver/daemon after a ``workspace.yaml`` bind-mount change. Otherwise pass
    ``service`` or rely on defaults (`DAGSTER_COMPOSE_FILE` +
    `DAGSTER_COMPOSE_USER_CODE_SERVICE`; mount that compose dir into dagster-mcp).

    Set ``compose_project`` (or ``DAGSTER_COMPOSE_PROJECT``) to the same
    ``docker compose -p`` name used on the host (default ``dagster`` when the file
    lives in a folder named ``dagster``).
    """
    cf = (compose_file or DAGSTER_COMPOSE_FILE or "").strip()
    proj = (compose_project or DAGSTER_COMPOSE_PROJECT or "").strip()
    if not cf:
        raise ValueError(
            "compose_file is required (or set DAGSTER_COMPOSE_FILE in dagster-mcp env)"
        )
    if services is not None:
        svcs = [str(s).strip() for s in services if s and str(s).strip()]
        if not svcs:
            raise ValueError("services, when provided, must be a non-empty list")
    elif service and str(service).strip():
        svcs = [str(service).strip()]
    else:
        svcs = [DAGSTER_COMPOSE_USER_CODE_SERVICE]
    log.info(
        "tool compose_force_recreate compose_file=%r services=%r with_build=%s",
        cf,
        svcs,
        with_build,
    )
    t0 = time.perf_counter()
    try:
        p = Path(cf)
        if not p.is_file():
            raise FileNotFoundError(
                f"compose file not found: {cf!r} (mount your compose directory into "
                "dagster-mcp and set DAGSTER_COMPOSE_FILE accordingly)"
            )
        result = docker_ops.compose_force_recreate(
            compose_file=p,
            services=svcs,
            with_build=with_build,
            project_name=proj or None,
        )
        log.info(
            "compose_force_recreate ok services=%s ms=%.2f",
            svcs,
            (time.perf_counter() - t0) * 1000,
        )
        return _json({"ok": True, "compose_file": str(p), "services": svcs, **result})
    except Exception as exc:
        log.exception("compose_force_recreate failed")
        return _err(exc, compose_file=cf)


@mcp.tool()
def user_code_refresh(
    project: str | None = None,
    image_name: str | None = None,
    tag: str | None = None,
    no_cache: bool = False,
) -> str:
    """Build the code-location image and recreate the ``dagster_user_code`` container.

    Runs:

    1. ``docker build`` on *project* (default ``DAGSTER_USER_CODE_BUILD_PROJECT``, usually
       ``datasyn``), tagging as *image_name* (default ``DAGSTER_USER_CODE_IMAGE_NAME``,
       usually ``dagster_user_code_image``) — same as ``build_image``.
    2. ``docker compose … up -d --no-build --force-recreate`` for
       ``DAGSTER_COMPOSE_USER_CODE_SERVICE`` (default ``dagster_user_code``) using
       ``DAGSTER_COMPOSE_FILE`` and ``DAGSTER_COMPOSE_PROJECT``.

    Requires ``DAGSTER_COMPOSE_FILE`` to exist inside this container (mount host
    ``infra/dagster`` at ``/dagster-compose`` — see ``infra/dagster/docker-compose.yaml``).
    """
    proj = (project or DAGSTER_USER_CODE_BUILD_PROJECT).strip()
    img_arg = (image_name or DAGSTER_USER_CODE_IMAGE_NAME).strip()
    cf = (DAGSTER_COMPOSE_FILE or "").strip()
    log.info(
        "tool user_code_refresh project=%r image_name=%r tag=%r compose_file=%r",
        proj,
        img_arg,
        tag,
        cf,
    )
    t0 = time.perf_counter()
    try:
        scaffold._ensure_project(PROJECTS_ROOT, proj)  # noqa: SLF001
        image = _full_image_ref(proj, tag=tag, image_name=img_arg)
        steps: list[dict[str, Any]] = [
            {
                "step": "build_image",
                "result": _build_project_image(
                    context_dir=PROJECTS_ROOT / proj,
                    primary_tag=image,
                    no_cache=no_cache,
                    pull=False,
                ),
            }
        ]
        if not cf:
            raise ValueError(
                "DAGSTER_COMPOSE_FILE is not set (mount infra/dagster into dagster-mcp; "
                "see infra/dagster/docker-compose.yaml)"
            )
        p = Path(cf)
        if not p.is_file():
            raise FileNotFoundError(
                f"compose file not found: {cf!r} (mount ../infra/dagster:/dagster-compose:ro "
                "and set DAGSTER_COMPOSE_FILE=/dagster-compose/docker-compose.yaml)"
            )
        proj_name = (DAGSTER_COMPOSE_PROJECT or "").strip() or None
        steps.append(
            {
                "step": "compose_force_recreate",
                "result": docker_ops.compose_force_recreate(
                    compose_file=p,
                    services=[DAGSTER_COMPOSE_USER_CODE_SERVICE],
                    with_build=False,
                    project_name=proj_name,
                ),
            }
        )
        log.info(
            "user_code_refresh ok image=%s ms=%.2f",
            image,
            (time.perf_counter() - t0) * 1000,
        )
        return _json(
            {
                "ok": True,
                "image": image,
                "compose_file": str(p),
                "services": [DAGSTER_COMPOSE_USER_CODE_SERVICE],
                "compose_project": proj_name or "",
                "steps": steps,
            }
        )
    except Exception as exc:
        log.exception("user_code_refresh failed")
        return _err(exc, project=proj)


@mcp.tool()
def stop(project: str) -> str:
    """``docker stop`` the project container (does not remove it)."""
    name = _container_for(project)
    log.info("tool stop project=%r container=%s", project, name)
    try:
        return _json({"ok": True, "container": name, **docker_ops.stop_container(name)})
    except Exception as exc:
        log.exception("stop failed")
        return _err(exc, project=project)


@mcp.tool()
def remove(
    project: str,
    remove_image: bool = False,
    tag: str | None = None,
    image_name: str | None = None,
) -> str:
    """``docker rm -f`` the project container (and optionally its image)."""
    name = _container_for(project)
    log.info("tool remove project=%r container=%s remove_image=%s", project, name, remove_image)
    try:
        out: dict[str, Any] = {"ok": True, "container": name, "rm": docker_ops.remove_container(name)}
        if remove_image:
            out["image_rm"] = docker_ops.remove_image(
                _full_image_ref(project, tag=tag, image_name=image_name)
            )
        return _json(out)
    except Exception as exc:
        log.exception("remove failed")
        return _err(exc, project=project)


@mcp.tool()
def logs(project: str, tail: int = 200) -> str:
    """Tail the project container's logs (last ``tail`` lines)."""
    name = _container_for(project)
    log.info("tool logs project=%r container=%s tail=%s", project, name, tail)
    try:
        return _json({"ok": True, "container": name, **docker_ops.container_logs(name, tail=tail)})
    except Exception as exc:
        log.exception("logs failed")
        return _err(exc, project=project)


@mcp.tool()
def status(project: str | None = None) -> str:
    """List Docker containers labeled ``datacyber.dagster.project`` (optionally filter)."""
    label = f"datacyber.dagster.project={project}" if project else "datacyber.dagster.project"
    log.info("tool status filter=%s", label)
    try:
        result = docker_ops.container_status(label_filter=label)
        rows: list[dict[str, Any]] = []
        for line in (result.get("stdout") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"raw": line})
        return _json({"ok": True, "filter": label, "containers": rows})
    except Exception as exc:
        log.exception("status failed")
        return _err(exc)


@mcp.tool()
def daemon_info() -> str:
    """Return ``docker info`` (confirms the host daemon socket is reachable)."""
    log.info("tool daemon_info")
    try:
        return _json({"ok": True, **docker_ops.daemon_info()})
    except Exception as exc:
        log.exception("daemon_info failed")
        return _err(exc)


def _catalog_preview(sql: str, max_len: int = 800) -> str:
    s = (sql or "").strip().replace("\n", " ")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


@mcp.tool()
def catalog_get_schema() -> str:
    """Return ``public`` schema as JSON: tables, columns, and foreign keys (metadata catalog)."""
    t0 = time.perf_counter()
    try:
        with catalog_connect(autocommit=True) as conn:
            doc = fetch_public_schema(conn)
        log.info(
            "catalog_get_schema ok tables=%s ms=%.2f",
            len(doc.get("tables") or {}),
            (time.perf_counter() - t0) * 1000,
        )
        return json.dumps(doc, indent=2, default=str)
    except Exception as exc:
        log.exception("catalog_get_schema failed")
        return json.dumps(
            {"error": str(exc), "schema": "public", "tables": {}, "foreign_keys": []},
            indent=2,
        )


@mcp.tool()
def catalog_execute_query(sql: str, max_rows: int = 100) -> str:
    """
    Run one SQL statement against the metadata catalog database.

    * **SELECT** (or ``WITH … SELECT``): returns ``{"rows": [...], "truncated": bool, "max_rows": N}``.
    * **INSERT / UPDATE / DELETE**: returns ``{"ok": true, "rowcount": N}`` (use ``RETURNING`` if you need rows).

    Destructive DDL is rejected (same policy as the former catalog-mcp).
    """
    lim = max(1, min(int(max_rows or 100), LIST_CAP_CATALOG))
    err = validate_catalog_sql(sql)
    if err:
        log.warning("catalog_execute_query rejected: %s", err)
        return json.dumps({"error": err}, indent=2)

    q = (sql or "").strip()
    log.info("catalog_execute_query max_rows=%s preview=%r", lim, _catalog_preview(q))
    t0 = time.perf_counter()
    try:
        with catalog_connect(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(q)
                if cur.description:
                    rows = cur.fetchmany(lim + 1)
                    truncated = len(rows) > lim
                    rows_out: list[dict[str, Any]] = [dict(r) for r in rows[:lim]]
                    payload = {"rows": rows_out, "truncated": truncated, "max_rows": lim}
                else:
                    payload = {"ok": True, "rowcount": cur.rowcount}
        log.info("catalog_execute_query ok ms=%.2f", (time.perf_counter() - t0) * 1000)
        return json.dumps(payload, indent=2, default=str)
    except Exception as exc:
        log.exception("catalog_execute_query failed")
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    if not PROJECTS_ROOT.exists():
        return PlainTextResponse(
            f"projects root missing: {PROJECTS_ROOT}", status_code=503
        )
    return PlainTextResponse("ok")


if __name__ == "__main__":
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    log.info(
        "starting dagster-mcp host=%s port=%s path=%s projects_root=%s network=%s",
        HOST,
        PORT,
        MCP_HTTP_PATH,
        PROJECTS_ROOT,
        PROJECT_NETWORK,
    )
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path=MCP_HTTP_PATH,
    )
