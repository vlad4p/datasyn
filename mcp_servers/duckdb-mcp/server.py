"""DuckDB warehouse MCP server (FastMCP, HTTP). Standalone — no imports from the main agent."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

_env = Path(__file__).resolve().parent / ".env"
if _env.is_file():
    load_dotenv(_env)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [duckdb-mcp] %(message)s",
    stream=sys.stderr,
    force=True,
)
log = logging.getLogger("duckdb-mcp")

DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb")
SQL_ROW_CAP = max(1, int(os.environ.get("SQL_ROW_CAP", "500")))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8040"))
MCP_HTTP_PATH = os.environ.get("MCP_HTTP_PATH", "/mcp")
DATA_LOCAL_ROOT = Path(os.environ.get("DATA_LOCAL_ROOT", "/data-local")).resolve()


def _fix_data_load_typo(s: str) -> str:
    """Map typo `data-load` to canonical mount name `data-local` (host path is /data-local, not /data-load)."""
    if "data-load" not in s:
        return s
    out = s.replace("data-load", "data-local")
    log.info("normalized path typo data-load -> data-local (sample): %r -> %r", s[:120], out[:120])
    return out


mcp = FastMCP(
    name="duckdb-mcp",
    instructions=(
        "Datacyber DuckDB warehouse. Tools: warehouse_list_tables, warehouse_query, data_local_ls. "
        "All loads and DDL go through warehouse_query using DuckDB SQL. "
        "There is NO database_ingest_csv or ingest_csv tool—do not assume those exist. "
        "Prefer comma-separated CSV for loads; semicolon text or Excel xls/xlsx may be normalized to CSV "
        "with pandas (see project skills ingest-pandas-normalize), then read_csv_auto on the CSV. "
        "Use read_csv/read_csv_auto/COPY with path and options. "
        "CREATE TABLE schema.name AS SELECT * FROM read_csv_auto(...). "
        "Use warehouse_list_tables when schema is unknown. "
        "To list directory contents under the host data mount, prefer data_local_ls(path, recursive=False, max_depth=3) — "
        f"read-only, confined to {DATA_LOCAL_ROOT}. When the caller asks to include subfolders or wants files "
        "inside nested directories, call data_local_ls(path, recursive=True). "
        "IMPORTANT: the mount is named **data-local** (local), NOT **data-load** (load)—a common typo. "
        "Alternatively use warehouse_query with DuckDB glob: glob('/data-local/*') lists only direct children; "
        "for nested paths use glob('/data-local/subdir/*') or glob('/data-local/**/*.txt')."
    ),
)


def _connect() -> duckdb.DuckDBPyConnection:
    parent = os.path.dirname(DUCKDB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return duckdb.connect(DUCKDB_PATH)


def _resolve_under_data_local(path: str) -> tuple[Path | None, str | None]:
    """Resolve user path to an absolute path under DATA_LOCAL_ROOT, or return (None, error)."""
    raw = _fix_data_load_typo((path or "").strip() or str(DATA_LOCAL_ROOT))
    p = Path(raw)
    if not p.is_absolute():
        p = DATA_LOCAL_ROOT / p
    try:
        resolved = p.resolve()
    except OSError as exc:
        return None, f"Error: cannot resolve path: {exc}"
    try:
        resolved.relative_to(DATA_LOCAL_ROOT)
    except ValueError:
        return None, (
            f"Error: path must stay under data root {DATA_LOCAL_ROOT} (refusing {resolved})"
        )
    return resolved, None


def _rows_to_text(columns: list[str], rows: list[tuple[object, ...]]) -> str:
    if not rows:
        return "(no rows)"
    header = " | ".join(columns)
    lines = [header, "-" * max(len(header), 8)]
    for row in rows[:SQL_ROW_CAP]:
        cells = [str(v) if v is not None else "NULL" for v in row]
        lines.append(" | ".join(cells))
    if len(rows) > SQL_ROW_CAP:
        lines.append(f"... truncated to {SQL_ROW_CAP} rows (SQL_ROW_CAP)")
    return "\n".join(lines)


@mcp.tool()
def warehouse_list_tables() -> str:
    """List base tables and views in the DuckDB database."""
    log.info("tool warehouse_list_tables start duckdb_path=%s", DUCKDB_PATH)
    t0 = time.perf_counter()
    con = _connect()
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
        out = _rows_to_text(cols, rows)
        log.info(
            "tool warehouse_list_tables ok rows=%s ms=%.2f",
            len(rows),
            (time.perf_counter() - t0) * 1000,
        )
        return out
    finally:
        con.close()


def _classify(child: Path) -> str:
    try:
        if child.is_symlink():
            return "symlink"
        if child.is_dir():
            return "directory"
        return "file"
    except OSError:
        return "unknown"


def _safe_size(child: Path) -> str:
    try:
        if child.is_file():
            return str(child.stat().st_size)
    except OSError:
        return "?"
    return ""


def _walk_data_local(
    root: Path, max_depth: int
) -> tuple[list[tuple[str, str, str]], bool]:
    """Depth-first walk under ``root`` (which must already be confined to DATA_LOCAL_ROOT).

    Returns ``(rows, truncated)`` where each row is ``(relpath, type, size_bytes)`` and ``relpath`` is
    relative to ``DATA_LOCAL_ROOT`` (e.g. ``EPH_usu_3_Trim_2025_txt/usu_hogar_T325.txt``). Depth 0 lists
    only ``root``'s children. Hits ``SQL_ROW_CAP`` → truncation flag.
    """
    rows: list[tuple[str, str, str]] = []
    truncated = False

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
            if len(rows) >= SQL_ROW_CAP:
                truncated = True
                return
            try:
                resolved = child.resolve()
                resolved.relative_to(DATA_LOCAL_ROOT)
            except ValueError:
                log.warning("walk skip entry outside root: %s", child)
                continue
            except OSError as exc:
                log.warning("walk skip %s: %s", child, exc)
                continue
            kind = _classify(child)
            size_s = _safe_size(child)
            try:
                rel = str(child.resolve().relative_to(DATA_LOCAL_ROOT))
            except ValueError:
                rel = child.name
            rows.append((rel, kind, size_s))
            if kind == "directory" and depth < max_depth:
                _recurse(child, depth + 1)

    _recurse(root, 0)
    return rows, truncated


@mcp.tool()
def data_local_ls(
    path: str = "/data-local",
    recursive: bool = False,
    max_depth: int = 3,
) -> str:
    """List files and subdirectories under the host data mount (read-only `ls`-style listing).

    Args:
        path: Directory to list. Absolute under `/data-local` or relative to the data root
            (e.g. `EPH_usu_3_Trim_2025_txt`). Paths are confined to `DATA_LOCAL_ROOT`.
        recursive: If ``True``, descend into subdirectories up to ``max_depth`` levels and emit a tree
            of entries with paths **relative to `/data-local`**. Use this when the caller asks to
            "include subfolders" or wants to see files inside nested directories in one call.
        max_depth: Max recursion depth when ``recursive`` is true (1 = direct children of subfolders).
            Ignored otherwise. Capped to 8 to prevent runaway walks.

    Output columns: ``name`` (path), ``type`` (file|directory|symlink), ``size_bytes``.
    Entries are capped at ``SQL_ROW_CAP`` to keep responses bounded.
    """
    log.info(
        "tool data_local_ls path_arg=%r recursive=%s max_depth=%s data_root=%s",
        path,
        recursive,
        max_depth,
        DATA_LOCAL_ROOT,
    )
    t0 = time.perf_counter()
    target, err = _resolve_under_data_local(path)
    if err:
        log.warning("data_local_ls resolve failed: %s", err)
        return err
    assert target is not None
    if not target.exists():
        return f"Error: path does not exist: {target}"
    if not target.is_dir():
        return f"Error: not a directory: {target}"

    if recursive:
        depth = max(1, min(int(max_depth or 1), 8))
        rows, was_truncated = _walk_data_local(target, depth)
    else:
        rows = []
        was_truncated = False
        try:
            for child in sorted(target.iterdir(), key=lambda x: x.name.lower()):
                try:
                    resolved = child.resolve()
                    resolved.relative_to(DATA_LOCAL_ROOT)
                except ValueError:
                    log.warning("data_local_ls skip entry outside root: %s", child)
                    continue
                except OSError as exc:
                    log.warning("data_local_ls skip %s: %s", child, exc)
                    continue
                rows.append((child.name, _classify(child), _safe_size(child)))
                if len(rows) >= SQL_ROW_CAP:
                    was_truncated = True
                    break
        except OSError as exc:
            log.exception("data_local_ls list failed")
            return f"Error: {type(exc).__name__}: {exc}"

    if not rows:
        return f"(empty directory: {target})"

    out = _rows_to_text(["name", "type", "size_bytes"], rows)
    if was_truncated:
        out += f"\n... truncated to {SQL_ROW_CAP} entries (SQL_ROW_CAP)"

    log.info(
        "tool data_local_ls ok entries=%s recursive=%s ms=%.2f",
        len(rows),
        recursive,
        (time.perf_counter() - t0) * 1000,
    )
    return out


@mcp.tool()
def warehouse_query(sql: str) -> str:
    """Execute DuckDB SQL (DDL/DML/SELECT). Use for ingest: read_csv_auto/read_csv/COPY, CREATE TABLE ... AS, CREATE SCHEMA.

    Loads arbitrary delimiter-separated files by path; set delim for ';' or ','. Creating a new table does not require
    a pre-existing table—use CREATE TABLE ... AS SELECT ... FROM read_csv*(...).

    File listing: SELECT file FROM glob('pattern'). glob('/data-local/*') lists only direct children; to list files
    inside a subdirectory use glob('/data-local/subdir/*') or recursive globs (e.g. '/data-local/**/*.txt')."""
    text = _fix_data_load_typo(sql.strip())
    preview = text[:500] + ("…" if len(text) > 500 else "")
    log.info("tool warehouse_query start sql_len=%s preview=%r", len(text), preview)
    if not text:
        log.warning("tool warehouse_query empty sql")
        return "Error: empty SQL"
    if len(text) > 200_000:
        return "Error: SQL too long"
    t0 = time.perf_counter()
    con = _connect()
    try:
        cur = con.execute(text)
        if cur.description is None:
            log.info(
                "tool warehouse_query ok no result set ms=%.2f",
                (time.perf_counter() - t0) * 1000,
            )
            return "(statement executed; no result set)"
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
        out = _rows_to_text(columns, rows)
        log.info(
            "tool warehouse_query ok rows=%s cols=%s ms=%.2f",
            len(rows),
            columns,
            (time.perf_counter() - t0) * 1000,
        )
        return out
    except Exception as exc:
        log.exception("tool warehouse_query failed: %s", exc)
        return f"Error: {type(exc).__name__}: {exc}"
    finally:
        con.close()


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=HOST,
        port=PORT,
        path=MCP_HTTP_PATH,
    )
