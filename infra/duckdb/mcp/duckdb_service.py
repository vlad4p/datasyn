"""DuckDB connection and query helpers (Datasyn warehouse MCP).

Pattern inspired by ktanaka101/mcp-server-duckdb (single DB handle, execute path);
this service adds schema introspection and a confined data-mount listing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import duckdb

log = logging.getLogger("duckdb-mcp")


def _fix_data_load_typo(s: str) -> str:
    if "data-load" not in s:
        return s
    out = s.replace("data-load", "data-local")
    log.info("normalized path typo data-load -> data-local (sample): %r -> %r", s[:120], out[:120])
    return out


class DuckDBWarehouse:
    """Thin wrapper around a file-backed DuckDB database."""

    def __init__(self, db_path: str, *, sql_row_cap: int, data_local_root: Path) -> None:
        self.db_path = db_path
        self.sql_row_cap = max(1, int(sql_row_cap))
        self.data_local_root = Path(data_local_root).resolve()

    def connect(self) -> duckdb.DuckDBPyConnection:
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return duckdb.connect(self.db_path)

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
        con = self.connect()
        try:
            cur = con.execute(text)
            if cur.description is None:
                return "(statement executed; no result set)"
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return self.rows_to_text(columns, rows)
        finally:
            con.close()

    def get_schema(self) -> str:
        """Tables and views from information_schema (read-only introspection)."""
        con = self.connect()
        try:
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
        finally:
            con.close()

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
