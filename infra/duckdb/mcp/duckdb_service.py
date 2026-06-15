"""DuckDB connection and query helpers (Datasyn warehouse MCP).

Single persistent RW connection to ``warehouse.duckdb`` (Quack server owner).
MCP tools and ``quack_serve`` share this session.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb

log = logging.getLogger("duckdb-mcp")

_MEDALLION_SCHEMAS: tuple[str, ...] = ("bronze", "silver", "gold")


def _fix_data_load_typo(s: str) -> str:
    if "data-load" not in s:
        return s
    out = s.replace("data-load", "data-local")
    log.info("normalized path typo data-load -> data-local (sample): %r -> %r", s[:120], out[:120])
    return out


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _minio_endpoint_host() -> str | None:
    """Return MinIO host:port for DuckDB S3 ``ENDPOINT`` (no scheme)."""
    endpoint = (os.environ.get("MINIO_ENDPOINT") or "").strip()
    if not endpoint:
        return None
    if "://" in endpoint:
        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        port = parsed.port
        if port:
            return f"{host}:{port}"
        return host
    return endpoint.rstrip("/")


def _minio_credentials() -> tuple[str, str] | None:
    access_key = (
        (os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER") or "").strip()
    )
    secret_key = (
        (os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD") or "").strip()
    )
    if access_key and secret_key:
        return access_key, secret_key
    return None


class DuckDBWarehouse:
    """Persistent file-backed DuckDB warehouse (Quack server session)."""

    def __init__(self, db_path: str, *, sql_row_cap: int, data_local_root: Path) -> None:
        self.db_path = db_path
        self.sql_row_cap = max(1, int(sql_row_cap))
        self.data_local_root = Path(data_local_root).resolve()
        self._lock = threading.RLock()
        self._con: duckdb.DuckDBPyConnection | None = None

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            raise RuntimeError("DuckDB warehouse not opened — call open() first")
        return self._con

    def open(self) -> None:
        """Open the warehouse file and bootstrap medallion schemas (idempotent)."""
        with self._lock:
            if self._con is not None:
                return
            parent = os.path.dirname(self.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._con = duckdb.connect(self.db_path)
            for name in _MEDALLION_SCHEMAS:
                self._con.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS _datasyn_init (ready INTEGER DEFAULT 1)"
            )
            log.info("DuckDB warehouse opened at %s", self.db_path)

    def ensure_httpfs(self) -> None:
        with self._lock:
            con = self._connection()
            con.execute("INSTALL httpfs;")
            con.execute("LOAD httpfs;")

    def ensure_minio_s3_secret(self, secret_name: str = "minio_s3") -> bool:
        """Create or replace MinIO S3 secret when env credentials are present."""
        host = _minio_endpoint_host()
        creds = _minio_credentials()
        if not host or not creds:
            log.info("MinIO S3 secret skipped (MINIO_ENDPOINT or credentials unset)")
            return False
        access_key, secret_key = creds
        use_ssl = _as_bool(os.environ.get("MINIO_SECURE"), default=False)
        with self._lock:
            self.ensure_httpfs()
            con = self._connection()
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", secret_name):
                raise ValueError(f"invalid S3 secret name: {secret_name!r}")
            con.execute(
                f"""
                CREATE OR REPLACE SECRET {secret_name} (
                    TYPE S3,
                    KEY_ID {_sql_str(access_key)},
                    SECRET {_sql_str(secret_key)},
                    ENDPOINT {_sql_str(host)},
                    USE_SSL {"true" if use_ssl else "false"},
                    URL_STYLE 'path',
                    REGION 'us-east-1'
                );
                """
            )
            log.info("MinIO S3 secret %s configured (endpoint=%s)", secret_name, host)
            return True

    def ensure_quack_extension(self) -> None:
        with self._lock:
            con = self._connection()
            con.execute("INSTALL quack;")
            con.execute("LOAD quack;")

    def start_quack_server(
        self,
        bind_uri: str,
        *,
        token: str | None = None,
        allow_other_hostname: bool = True,
    ) -> str | None:
        """Start Quack HTTP listener on the persistent session. Returns auth token."""
        bind_uri = bind_uri.strip()
        with self._lock:
            self.ensure_quack_extension()
            con = self._connection()
            allow = "true" if allow_other_hostname else "false"
            if token:
                con.execute(
                    f"""
                    CALL quack_serve(
                        {_sql_str(bind_uri)},
                        allow_other_hostname => {allow},
                        token => {_sql_str(token)}
                    );
                    """
                )
                auth_token = token
            else:
                result = con.execute(
                    f"""
                    CALL quack_serve(
                        {_sql_str(bind_uri)},
                        allow_other_hostname => {allow}
                    );
                    """
                ).fetchall()
                auth_token = None
                if result and len(result[0]) >= 3:
                    auth_token = str(result[0][2]) if result[0][2] is not None else None
            log.info("Quack server listening on %s", bind_uri)
            return auth_token

    def rows_to_text(self, columns: list[str], rows: list[tuple[object, ...]]) -> str:
        if not rows:
            return "(no rows)"
        header = " | ".join(columns)
        lines = [header, "-" * max(len(header), 8)]
        for row in rows[: self.sql_row_cap]:
            cells = [str(v) if v is not None else "NULL" for v in row]
            lines.append(" | ".join(cells))
        if len(rows) > self.sql_row_cap:
            lines.append(f"... truncated to {self.sql_row_cap} rows (SQL_ROW_CAP)")
        return "\n".join(lines)

    def execute_query(self, sql: str) -> str:
        text = _fix_data_load_typo(sql.strip())
        if not text:
            return "Error: empty SQL"
        if len(text) > 200_000:
            return "Error: SQL too long"
        with self._lock:
            con = self._connection()
            cur = con.execute(text)
            if cur.description is None:
                return "(statement executed; no result set)"
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return self.rows_to_text(columns, rows)

    def get_schema(self) -> str:
        with self._lock:
            con = self._connection()
            rows = con.execute(
                """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name
                """
            ).fetchall()
            cols = ["table_schema", "table_name", "table_type"]
            return self.rows_to_text(cols, rows)

    def _resolve_under_data_local(self, path: str) -> tuple[Path | None, str | None]:
        raw = _fix_data_load_typo((path or "").strip() or str(self.data_local_root))
        p = Path(raw)
        if not p.is_absolute():
            p = self.data_local_root / p
        try:
            resolved = p.resolve()
        except OSError as exc:
            return None, f"Error: cannot resolve path: {exc}"
        try:
            resolved.relative_to(self.data_local_root)
        except ValueError:
            return None, f"Error: path must stay under data root {self.data_local_root} (refusing {resolved})"
        return resolved, None

    @staticmethod
    def _classify(child: Path) -> str:
        try:
            if child.is_symlink():
                return "symlink"
            if child.is_dir():
                return "directory"
            return "file"
        except OSError:
            return "unknown"

    @staticmethod
    def _safe_size(child: Path) -> str:
        try:
            if child.is_file():
                return str(child.stat().st_size)
        except OSError:
            return "?"
        return ""

    def _walk_data_local(
        self, root: Path, max_depth: int
    ) -> tuple[list[tuple[str, str, str]], bool]:
        rows: list[tuple[str, str, str]] = []
        truncated = False
        root_resolved = self.data_local_root

        def _recurse(current: Path, depth: int) -> None:
            nonlocal truncated
            if truncated:
                return
            try:
                entries = sorted(current.iterdir(), key=lambda x: x.name.lower())
            except OSError as exc:
                log.warning("walk skip %s: %s", current, exc)
                return
            for child in entries:
                if len(rows) >= self.sql_row_cap:
                    truncated = True
                    return
                try:
                    resolved = child.resolve()
                    resolved.relative_to(root_resolved)
                except ValueError:
                    log.warning("walk skip entry outside root: %s", child)
                    continue
                except OSError as exc:
                    log.warning("walk skip %s: %s", child, exc)
                    continue
                kind = self._classify(child)
                size_s = self._safe_size(child)
                try:
                    rel = str(child.resolve().relative_to(root_resolved))
                except ValueError:
                    rel = child.name
                rows.append((rel, kind, size_s))
                if kind == "directory" and depth < max_depth:
                    _recurse(child, depth + 1)

        _recurse(root, 0)
        return rows, truncated

    def list_data_mount(
        self,
        path: str = "/data-local",
        recursive: bool = False,
        max_depth: int = 3,
    ) -> str:
        target, err = self._resolve_under_data_local(path)
        if err:
            return err
        assert target is not None
        if not target.exists():
            return f"Error: path does not exist: {target}"
        if not target.is_dir():
            return f"Error: not a directory: {target}"

        if recursive:
            depth = max(1, min(int(max_depth or 1), 8))
            rows, was_truncated = self._walk_data_local(target, depth)
        else:
            rows = []
            was_truncated = False
            try:
                for child in sorted(target.iterdir(), key=lambda x: x.name.lower()):
                    try:
                        resolved = child.resolve()
                        resolved.relative_to(self.data_local_root)
                    except ValueError:
                        log.warning("list_data_mount skip entry outside root: %s", child)
                        continue
                    except OSError as exc:
                        log.warning("list_data_mount skip %s: %s", child, exc)
                        continue
                    rows.append((child.name, self._classify(child), self._safe_size(child)))
                    if len(rows) >= self.sql_row_cap:
                        was_truncated = True
                        break
            except OSError as exc:
                log.exception("list_data_mount list failed")
                return f"Error: {type(exc).__name__}: {exc}"

        if not rows:
            return f"(empty directory: {target})"

        out = self.rows_to_text(["name", "type", "size_bytes"], rows)
        if was_truncated:
            out += f"\n... truncated to {self.sql_row_cap} entries (SQL_ROW_CAP)"
        return out
