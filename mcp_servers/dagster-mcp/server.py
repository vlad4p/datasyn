"""Dagster MCP (FastMCP HTTP): scaffold Dagster projects, build images, deploy.

Tools (LangChain prefixes them with the MCP key ``dagster``):

- ``dagster_list_projects``   — list scaffolded projects under ``DAGSTER_PROJECTS_ROOT``.
- ``dagster_create_project``  — generate a new Dagster project (pyproject, Dockerfile,
                                 workspace, package layout, an example asset + job).
- ``dagster_add_asset``       — add a file-per-asset (auto-discovered).
- ``dagster_add_job``         — add a file-per-job using ``define_asset_job``.
- ``dagster_add_schedule``    — add a ``ScheduleDefinition`` linked to a job.
- ``dagster_add_sensor``      — add a ``@sensor`` linked to a job.
- ``dagster_build_image``     — ``docker build`` the project image on the host daemon
                                 (optional *image_name*, e.g. ``dagster_user_code_image``).
- ``dagster_compose_force_recreate`` — ``docker compose up -d --no-build --force-recreate``
                                 for an external stack (default: Ubika ``dagster_user_code``).
- ``dagster_deploy``          — run/replace the project container, attached to
                                 ``datacyber_mcp`` network.
- ``dagster_stop`` / ``dagster_remove`` / ``dagster_logs`` / ``dagster_status``
                                — container lifecycle helpers.

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

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8043"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")

PROJECTS_ROOT = Path(
    os.environ.get("DAGSTER_PROJECTS_ROOT", "/projects")
).resolve()
PROJECT_NETWORK = os.environ.get("DAGSTER_PROJECT_NETWORK", "datacyber_mcp")
IMAGE_PREFIX = os.environ.get("DAGSTER_IMAGE_PREFIX", "dagster").rstrip("/")
CONTAINER_PREFIX = os.environ.get("DAGSTER_CONTAINER_PREFIX", "dagster").rstrip("-")
DEFAULT_HOST_PORT = int(os.environ.get("DAGSTER_DEFAULT_HOST_PORT", "3001"))
WEBSERVER_PORT = int(os.environ.get("DAGSTER_WEBSERVER_PORT", "3000"))
# Semicolon-separated `src:dst[:mode]` mounts passed to `docker run -v` for
# `dagster_deploy` (paths are resolved on the **host** by the Docker daemon).
# Example (host shell before `compose up`):
#   export DAGSTER_DEPLOY_VOLUMES="datacyber-mcp_duckdb_data:/data;/abs/path/datacyber/data-local:/data-local:ro"
DAGSTER_DEPLOY_VOLUMES = os.environ.get(
    "DAGSTER_DEPLOY_VOLUMES",
    "datacyber-mcp_duckdb_data:/data",
)
UBIKA_DAGSTER_COMPOSE_FILE = os.environ.get(
    "UBIKA_DAGSTER_COMPOSE_FILE",
    "/ubika-dagster/docker-compose.yaml",
)
UBIKA_DAGSTER_USER_CODE_SERVICE = os.environ.get(
    "UBIKA_DAGSTER_USER_CODE_SERVICE",
    "dagster_user_code",
)
# Compose project name must match how the stack was first created from the host
# (directory name is ``dagster`` when the compose file lives in ``.../mvp/dagster/``).
UBIKA_DAGSTER_COMPOSE_PROJECT = os.environ.get("UBIKA_DAGSTER_COMPOSE_PROJECT", "dagster")

mcp = FastMCP(
    name="dagster-mcp",
    instructions=(
        "Datacyber Dagster MCP. Generates Dagster code-location projects under "
        "/projects/<name>/ (host-mounted) and drives the host Docker daemon "
        "through a mounted socket to build images and run/replace project "
        "containers attached to the `datacyber_mcp` network. "
        "Workflow: `create_project` → `add_asset` / `add_job` / `add_schedule` / "
        "`add_sensor` → `build_image` → `deploy` (idempotent: replaces any "
        "container with the same name). Each project's Dagster UI is exposed on "
        "the host port chosen at deploy time. Use `compose_force_recreate` after "
        "tagging an image (e.g. `dagster_user_code_image`) for an external Ubika "
        "compose stack mounted at `UBIKA_DAGSTER_COMPOSE_FILE`. The MCP itself never "
        "imports Dagster; it only generates code and shells out to `docker`."
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
    example asset and an example job. Build and deploy with
    ``dagster_build_image`` then ``dagster_deploy``.
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
        result = docker_ops.build_image(
            context_dir=ctx,
            tag=image,
            no_cache=no_cache,
            pull=pull,
        )
        log.info("build_image ok image=%s ms=%.2f", image, (time.perf_counter() - t0) * 1000)
        return _json({"ok": True, "image": image, "context": str(ctx), **result})
    except Exception as exc:
        log.exception("build_image failed")
        return _err(exc, project=project)


@mcp.tool()
def deploy(
    project: str,
    host_port: int = 0,
    container_port: int = 0,
    tag: str | None = None,
    image_name: str | None = None,
    rebuild: bool = False,
    no_cache: bool = False,
) -> str:
    """Run/replace the project container.

    - ``host_port=0`` (default) → use ``DAGSTER_DEFAULT_HOST_PORT``.
    - ``container_port=0`` (default) → use ``DAGSTER_WEBSERVER_PORT`` (e.g. ``3000``
      for ``dagster dev``). Set to ``4000`` when the image runs ``dagster api grpc``
      on that port (typical user-code image running ``dagster api grpc``).
    - ``rebuild=True`` runs ``build_image`` first (same *image_name* / *tag*).
    - ``image_name`` — optional fixed image ref; see ``dagster_build_image``.
    - The container is named ``<prefix>-<project>``, attached to the
      ``datacyber_mcp`` network so it can reach ``duckdb-mcp:8040`` /
      ``scrapper-mcp:8042`` / etc., and publishes ``host_port:container_port``.

    Idempotent: any existing container with the same name is removed first.
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
                    "result": docker_ops.build_image(
                        context_dir=PROJECTS_ROOT / project,
                        tag=image,
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

    Pass ``services`` (non-empty) to recreate several at once, e.g. user-code plus
    webserver/daemon after a ``workspace.yaml`` bind-mount change. Otherwise pass
    ``service`` or rely on defaults (Ubika: ``UBIKA_DAGSTER_COMPOSE_FILE`` +
    ``UBIKA_DAGSTER_USER_CODE_SERVICE``; mount that compose dir into dagster-mcp).

    Set ``compose_project`` (or ``UBIKA_DAGSTER_COMPOSE_PROJECT``) to the same
    ``docker compose -p`` name used on the host (default ``dagster`` when the file
    lives in a folder named ``dagster``).
    """
    cf = compose_file or UBIKA_DAGSTER_COMPOSE_FILE
    proj = compose_project or UBIKA_DAGSTER_COMPOSE_PROJECT
    if services is not None:
        svcs = [str(s).strip() for s in services if s and str(s).strip()]
        if not svcs:
            raise ValueError("services, when provided, must be a non-empty list")
    elif service and str(service).strip():
        svcs = [str(service).strip()]
    else:
        svcs = [UBIKA_DAGSTER_USER_CODE_SERVICE]
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
                f"compose file not found: {cf!r} (mount Ubika dagster dir into "
                "dagster-mcp, e.g. ../../ubika-infra/live/mvp/dagster:/ubika-dagster:ro)"
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
