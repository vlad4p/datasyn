"""Start the DuckDB built-in UI extension, then expose it on all interfaces via socat.

The ``ui`` HTTP server calls ``listen("localhost", port)`` (duckdb-ui ``http_server.cpp``).
It may bind **only IPv6** ``[::1]`` while **socat** ``TCP:localhost:…`` often resolves ``localhost``
to **127.0.0.1** first, so we **probe** ``localhost`` the same way as ``socket.connect`` and pass
an explicit backend to socat: ``TCP:127.0.0.1:PORT`` or ``TCP6:[::1]:PORT``.

DuckDB does not bind on ``0.0.0.0``; see https://github.com/duckdb/duckdb-ui/issues/22
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time

log = logging.getLogger("duckdb-ui")

DUCK_LOOPBACK_PORT = int(os.environ.get("DUCKDB_UI_DUCK_PORT", "4213"))
PROXY_PORT = int(os.environ.get("DUCKDB_UI_PROXY_PORT", "4214"))
DB_PATH = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb")
HOME_DIR = os.environ.get("DUCKDB_UI_HOME", "/tmp/duckdb-ui-home")

# Optional override, e.g. ``TCP6:[::1]:4213`` or ``TCP:127.0.0.1:4213`` (skip auto-detection).
SOCAT_BACKEND = os.environ.get("DUCKDB_UI_SOCAT_BACKEND", "").strip()


def _socat_backend_spec(port: int) -> str | None:
    """Return a socat address for the DuckDB listener, or None if nothing accepts TCP yet."""
    try:
        infos = socket.getaddrinfo(
            "localhost",
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError:
        return None
    for res in infos:
        af, socktype, proto, _canon, sa = res
        sock: socket.socket | None = None
        try:
            sock = socket.socket(af, socktype, proto)
            sock.settimeout(2.0)
            sock.connect(sa)
        except OSError:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        if af == socket.AF_INET:
            host = sa[0]
            return f"TCP:{host}:{port}"
        if af == socket.AF_INET6:
            host = sa[0]
            return f"TCP6:[{host}]:{port}"
    return None


def _wait_socat_backend(port: int, *, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if attempt % 25 == 1:
            log.info("waiting for UI on localhost:%s (%.0fs left)", port, deadline - time.monotonic())
        spec = _socat_backend_spec(port)
        if spec:
            log.info("socat backend (auto): %s", spec)
            return spec
        time.sleep(0.4)
    raise TimeoutError(f"no connectable localhost:{port} within {timeout_s}s")


def _run_worker() -> None:
    import duckdb

    os.makedirs(HOME_DIR, exist_ok=True)
    os.environ.setdefault("HOME", HOME_DIR)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    log.info("worker opening %s (UI binds localhost:%s)", DB_PATH, DUCK_LOOPBACK_PORT)

    con = duckdb.connect(DB_PATH)
    try:
        for label, sql in (
            ("install ui (core)", "INSTALL ui;"),
            ("install ui (community)", "INSTALL ui FROM community;"),
        ):
            try:
                con.execute(sql)
                log.info("%s ok", label)
                break
            except Exception as exc:
                log.warning("%s: %s", label, exc)
        con.execute("LOAD ui;")
        log.info("LOAD ui ok")
        con.execute("CALL start_ui();")
        time.sleep(2.0)
        log.info("CALL start_ui() done; holding connection open for UI server on localhost:%s", DUCK_LOOPBACK_PORT)
        while True:
            time.sleep(3600.0)
    finally:
        con.close()


def _run_supervisor() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    log.info(
        "supervisor: will proxy 0.0.0.0:%s -> <resolved localhost>:%s",
        PROXY_PORT,
        DUCK_LOOPBACK_PORT,
    )
    worker = subprocess.Popen([sys.executable, __file__, "worker"])
    try:
        if SOCAT_BACKEND:
            backend = SOCAT_BACKEND
            log.info("socat backend (from DUCKDB_UI_SOCAT_BACKEND): %s", backend)
        else:
            try:
                backend = _wait_socat_backend(DUCK_LOOPBACK_PORT, timeout_s=180.0)
            except TimeoutError as exc:
                log.error("%s", exc)
                worker.terminate()
                raise SystemExit(1) from exc
        log.info("starting socat TCP-LISTEN:%s (0.0.0.0) -> %s", PROXY_PORT, backend)
        socat = subprocess.Popen(
            [
                "socat",
                f"TCP-LISTEN:{PROXY_PORT},fork,bind=0.0.0.0,reuseaddr",
                backend,
            ]
        )
        time.sleep(0.3)
        if socat.poll() is not None:
            log.error("socat exited immediately code=%s", socat.returncode)
            worker.terminate()
            raise SystemExit(1)
        log.info("socat running; open host URL mapped to container port %s (default http://127.0.0.1:4213)", PROXY_PORT)
        try:
            code = worker.wait()
            log.error("worker exited unexpectedly code=%s", code)
            raise SystemExit(code or 1)
        finally:
            socat.terminate()
            try:
                socat.wait(timeout=5)
            except subprocess.TimeoutExpired:
                socat.kill()
    except KeyboardInterrupt:
        worker.terminate()
        raise


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        _run_worker()
    else:
        _run_supervisor()
