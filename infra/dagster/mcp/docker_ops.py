"""Thin subprocess wrapper around the host Docker CLI.

The MCP container mounts the host's ``/var/run/docker.sock`` so the ``docker``
CLI inside the container talks to the **host** Docker daemon. Every helper
returns a structured dict; commands are never chained via ``&&`` so each step
appears clearly in the manifest the MCP returns to the caller.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = int(os.environ.get("DAGSTER_DOCKER_TIMEOUT", "900"))


class DockerError(RuntimeError):
    """Raised when a Docker subprocess returns a non-zero exit code."""


def _docker_bin() -> str:
    path = shutil.which("docker")
    if not path:
        raise DockerError(
            "docker CLI not found on PATH; rebuild the dagster-mcp image with the "
            "Dockerfile in this repo (it installs docker-ce-cli)."
        )
    return path


def _run(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    check: bool = True,
) -> dict[str, Any]:
    cmd = [_docker_bin(), *args]
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    payload: dict[str, Any] = {
        "cmd": shlex.join(cmd),
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if check and proc.returncode != 0:
        raise DockerError(
            f"docker {' '.join(args)!r} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return payload


def daemon_info() -> dict[str, Any]:
    """`docker info -f json` — confirms the host daemon is reachable."""
    return _run(["info", "-f", "{{json .}}"])


def build_image(
    *,
    context_dir: str | Path,
    tag: str,
    no_cache: bool = False,
    pull: bool = False,
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
    args = ["build", "-t", tag]
    for et in extra_tags or []:
        et = (et or "").strip()
        if et and et != tag:
            args.extend(["-t", et])
    if no_cache:
        args.append("--no-cache")
    if pull:
        args.append("--pull")
    args.append(str(context_dir))
    return _run(args)


def push_image(image: str) -> dict[str, Any]:
    """``docker push <image>`` (registry-authenticated host daemon)."""
    img = (image or "").strip()
    if not img:
        raise ValueError("image is required")
    return _run(["push", img])


def remove_container(name: str, *, force: bool = True) -> dict[str, Any]:
    args = ["rm"]
    if force:
        args.append("-f")
    args.append(name)
    return _run(args, check=False)


def container_exists(name: str) -> bool:
    out = _run(
        ["ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        check=False,
    )
    return name in (out.get("stdout") or "").splitlines()


def run_dagster_container(
    *,
    name: str,
    image: str,
    network: str,
    host_port: int,
    container_port: int,
    project: str,
    extra_env: dict[str, str] | None = None,
    extra_labels: dict[str, str] | None = None,
    volumes: list[str] | None = None,
) -> dict[str, Any]:
    """Start a fresh Dagster project container.

    Always replaces an existing container with the same name; safe to call
    repeatedly as a "redeploy" primitive.
    """
    if container_exists(name):
        remove_container(name, force=True)
    args: list[str] = [
        "run",
        "-d",
        "--name",
        name,
        "--restart",
        "unless-stopped",
        "--network",
        network,
        "--hostname",
        name,
        "-p",
        f"{host_port}:{container_port}",
        "-l",
        f"datacyber.dagster.project={project}",
    ]
    for k, v in (extra_labels or {}).items():
        args.extend(["-l", f"{k}={v}"])
    for k, v in (extra_env or {}).items():
        args.extend(["-e", f"{k}={v}"])
    for vol in volumes or []:
        vol = vol.strip()
        if vol:
            args.extend(["-v", vol])
    args.append(image)
    return _run(args)


def container_logs(name: str, *, tail: int = 200, since: str | None = None) -> dict[str, Any]:
    args = ["logs", "--tail", str(int(tail))]
    if since and since.strip():
        args.extend(["--since", since.strip()])
    args.append(name)
    return _run(args, check=False)


def container_status(
    label_filter: str | None = None,
    *,
    name_filter: str | None = None,
    all_containers: bool = True,
) -> dict[str, Any]:
    args = ["ps", "-a", "--format", "{{json .}}"]
    if not all_containers:
        args = ["ps", "--format", "{{json .}}"]
    if label_filter:
        args.extend(["--filter", f"label={label_filter}"])
    if name_filter:
        args.extend(["--filter", f"name={name_filter}"])
    return _run(args)


def stop_container(name: str) -> dict[str, Any]:
    return _run(["stop", name], check=False)


def remove_image(image: str) -> dict[str, Any]:
    return _run(["image", "rm", image], check=False)


def compose_force_recreate(
    *,
    compose_file: str | Path,
    services: list[str],
    with_build: bool = False,
    project_name: str | None = None,
) -> dict[str, Any]:
    """``docker compose … up -d --force-recreate`` for one or more services (host daemon)."""
    cf = Path(compose_file).resolve()
    cwd = cf.parent
    if not services:
        raise ValueError("services must be non-empty")
    args = ["compose"]
    if project_name:
        args.extend(["-p", project_name])
    args.extend(["-f", str(cf), "up", "-d"])
    if with_build:
        args.append("--build")
    else:
        args.append("--no-build")
    args.append("--force-recreate")
    args.extend(services)
    return _run(args, cwd=cwd)


def compose_ps(
    *,
    compose_file: str | Path,
    project_name: str | None = None,
    services: list[str] | None = None,
    all_containers: bool = True,
) -> dict[str, Any]:
    """``docker compose ps --format json`` for a mounted Compose stack."""
    cf = Path(compose_file).resolve()
    cwd = cf.parent
    args = ["compose"]
    if project_name:
        args.extend(["-p", project_name])
    args.extend(["-f", str(cf), "ps"])
    if all_containers:
        args.append("--all")
    args.extend(["--format", "json"])
    args.extend([s for s in services or [] if s])
    return _run(args, cwd=cwd, check=False)


def compose_logs(
    *,
    compose_file: str | Path,
    services: list[str],
    tail: int = 200,
    since: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """``docker compose logs`` for one or more services in a mounted stack."""
    cf = Path(compose_file).resolve()
    cwd = cf.parent
    args = ["compose"]
    if project_name:
        args.extend(["-p", project_name])
    args.extend(["-f", str(cf), "logs", "--no-color", "--tail", str(int(tail))])
    if since and since.strip():
        args.extend(["--since", since.strip()])
    args.extend(services)
    return _run(args, cwd=cwd, check=False)
