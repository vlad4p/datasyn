"""Quack-protocol sync: pull tables from external DuckDB into the main warehouse via MCP.

All SQL runs as **one statement per** ``duckdb_execute_query`` call on the main
``duckdb-mcp`` process (which holds the RW ``warehouse.duckdb`` and can ATTACH
external Quack sources).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient as MultiServerToolClient

from agent.utils.mcp_connections import load_mcp_tool_connections
from agent.utils.warehouse_schema import _extract_tool_text

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_SOURCE_SCHEMAS = ("bronze", "silver", "gold")
_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS medallion.sync_registry (
    id BIGINT,
    source_name VARCHAR,
    source_uri VARCHAR,
    source_fqn VARCHAR,
    target_fqn VARCHAR,
    row_count BIGINT,
    status VARCHAR,
    error_message VARCHAR,
    synced_at TIMESTAMP
)
""".strip()


def _project_root() -> Path:
    try:
        from agent.config import settings

        return settings.project_root
    except Exception:
        return Path(__file__).resolve().parents[2]


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_ident(name: str, *, label: str) -> str:
    cleaned = (name or "").strip()
    if not _IDENT_RE.match(cleaned):
        raise ValueError(f"invalid {label} identifier: {name!r}")
    return cleaned


@dataclass
class SyncTableSpec:
    source_schema: str
    source_table: str
    target_table: str | None = None

    @property
    def source_fqn(self) -> str:
        return f"{self.source_schema}.{self.source_table}"

    def target_name(self) -> str:
        return self.target_table or self.source_table


@dataclass
class SyncSource:
    name: str
    alias: str
    quack_uri: str
    quack_token: str
    target_schema: str = "bronze"
    tables: list[SyncTableSpec] = field(default_factory=list)
    source_schemas: list[str] = field(default_factory=lambda: list(_DEFAULT_SOURCE_SCHEMAS))
    enabled: bool = True
    disable_ssl: bool = True


def _env_for_source(name: str, *, env_prefix: str | None = None) -> tuple[str, str]:
    """Resolve (uri_env, token_env) names for a source."""
    prefix = (env_prefix or f"SYNC_{name.upper()}").strip().upper()
    prefix = re.sub(r"[^A-Z0-9_]", "_", prefix)
    return f"{prefix}_QUACK_URI", f"{prefix}_QUACK_TOKEN"


def load_sync_sources(manifest_path: Path | None = None) -> list[SyncSource]:
    """Load non-secret source defs from YAML and resolve credentials from env."""
    root = _project_root()
    path = manifest_path or root / "config" / "sync_sources.yaml"
    if not path.is_file():
        logger.warning("sync manifest missing: %s", path)
        return []

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required for sync_sources.yaml (uv sync)") from exc

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("sources") or []
    if not isinstance(entries, list):
        raise ValueError("config/sync_sources.yaml: 'sources' must be a list")

    default_target = (os.environ.get("SYNC_TARGET_SCHEMA") or "bronze").strip() or "bronze"
    out: list[SyncSource] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        enabled = entry.get("enabled", True)
        if enabled is False or str(enabled).strip().lower() in ("0", "false", "no"):
            continue

        env_prefix = entry.get("env_prefix")
        uri_env = str(entry.get("quack_uri_env") or "").strip() or _env_for_source(
            name, env_prefix=str(env_prefix) if env_prefix else None
        )[0]
        token_env = str(entry.get("quack_token_env") or "").strip() or _env_for_source(
            name, env_prefix=str(env_prefix) if env_prefix else None
        )[1]
        # Also accept global EXTERNAL fallbacks for a single source named "external"
        uri = (os.environ.get(uri_env) or "").strip()
        token = (os.environ.get(token_env) or "").strip()
        if not uri and name.lower() == "external":
            uri = (os.environ.get("EXTERNAL_QUACK_URI") or "").strip()
        if not token and name.lower() == "external":
            token = (os.environ.get("EXTERNAL_QUACK_TOKEN") or "").strip()

        if not uri or not token:
            logger.warning(
                "sync source %r skipped: missing %s / %s",
                name,
                uri_env,
                token_env,
            )
            continue

        alias = _require_ident(str(entry.get("alias") or f"ext_{name}"), label="alias")
        target_schema = _require_ident(
            str(entry.get("target_schema") or default_target),
            label="target_schema",
        )
        schemas_raw = entry.get("source_schemas") or list(_DEFAULT_SOURCE_SCHEMAS)
        source_schemas = [_require_ident(str(s), label="source_schema") for s in schemas_raw]

        tables: list[SyncTableSpec] = []
        for t in entry.get("tables") or []:
            if not isinstance(t, dict):
                continue
            ss = _require_ident(str(t.get("source_schema") or ""), label="source_schema")
            st = _require_ident(str(t.get("source_table") or ""), label="source_table")
            tt = t.get("target_table")
            target_table = _require_ident(str(tt), label="target_table") if tt else None
            tables.append(SyncTableSpec(source_schema=ss, source_table=st, target_table=target_table))

        disable_ssl = str(entry.get("disable_ssl", True)).strip().lower() not in (
            "0",
            "false",
            "no",
        )
        out.append(
            SyncSource(
                name=name,
                alias=alias,
                quack_uri=uri,
                quack_token=token,
                target_schema=target_schema,
                tables=tables,
                source_schemas=source_schemas,
                enabled=True,
                disable_ssl=disable_ssl,
            )
        )
    return out


def _tool_arg_names(tool: Any) -> set[str]:
    """Collect argument names from a LangChain / MCP tool schema."""
    names: set[str] = set()
    schema = getattr(tool, "args_schema", None)
    if schema is not None:
        fields = getattr(schema, "model_fields", None) or getattr(schema, "__fields__", None)
        if isinstance(fields, dict):
            names.update(str(k) for k in fields)
        if isinstance(schema, dict):
            props = schema.get("properties")
            if isinstance(props, dict):
                names.update(str(k) for k in props)
            for key in ("required",):
                req = schema.get(key)
                if isinstance(req, list):
                    names.update(str(k) for k in req)
    # StructuredTool often exposes a JSON-schema-like ``args`` / ``tool_call_schema``
    for attr in ("args", "tool_call_schema", "input_schema"):
        blob = getattr(tool, attr, None)
        if isinstance(blob, dict):
            props = blob.get("properties") if "properties" in blob else blob
            if isinstance(props, dict):
                names.update(str(k) for k in props)
    return names


def _resolve_sql_arg_key(tool: Any) -> str:
    """duckdb-mcp ``execute_query`` takes ``sql`` (not ``query``). Prefer schema, else ``sql``."""
    names = _tool_arg_names(tool)
    for candidate in ("sql", "query", "statement"):
        if candidate in names:
            return candidate
    # Fleet / local duckdb-mcp contract is ``sql``; never default to ``query``.
    return "sql"


class _McpSql:
    """Thin wrapper: one SQL statement per duckdb_execute_query call."""

    def __init__(self) -> None:
        self._tool: Any | None = None
        self._arg_key: str = "sql"

    async def connect(self) -> None:
        client = MultiServerToolClient(load_mcp_tool_connections(), tool_name_prefix=True)
        tools = await client.get_tools()
        for t in tools:
            if str(getattr(t, "name", "") or "").strip() == "duckdb_execute_query":
                self._tool = t
                self._arg_key = _resolve_sql_arg_key(t)
                return
        raise RuntimeError("duckdb_execute_query tool not found (check mcp.json duckdb server)")

    async def execute(self, sql: str) -> str:
        if self._tool is None:
            raise RuntimeError("MCP SQL client not connected")
        text = sql.strip()
        if not text:
            return ""
        # Contract: one statement per call (no semicolon batches)
        if ";" in text.rstrip(";"):
            raise ValueError("only one SQL statement allowed per duckdb_execute_query call")
        payload = {self._arg_key: text.rstrip(";")}
        raw = await self._tool.ainvoke(payload)
        return _extract_tool_text(raw)


async def bootstrap_sync_registry(sql: _McpSql | None = None) -> None:
    """Ensure medallion schema + sync_registry exist on the main warehouse."""
    own = sql is None
    client = sql or _McpSql()
    if own:
        await client.connect()
    await client.execute("CREATE SCHEMA IF NOT EXISTS medallion")
    await client.execute(_REGISTRY_DDL)


def _parse_pipe_table(text: str) -> list[dict[str, str]]:
    """Parse a simple DuckDB pipe / markdown table into dict rows."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    if any(ln.startswith("Error:") for ln in lines[:3]):
        return []

    header_idx: int | None = None
    headers: list[str] = []
    for i, ln in enumerate(lines):
        if "|" not in ln:
            continue
        parts = [p.strip() for p in ln.strip("|").split("|")]
        if not parts:
            continue
        if all(set(p) <= {"-", ":", " "} for p in parts):
            continue
        headers = [h.lower() for h in parts]
        header_idx = i
        break

    rows: list[dict[str, str]] = []
    if header_idx is None or not headers:
        return rows
    for ln in lines[header_idx + 1 :]:
        if "|" not in ln:
            continue
        parts = [p.strip() for p in ln.strip("|").split("|")]
        if all(set(p) <= {"-", ":", " "} for p in parts):
            continue
        if len(parts) < len(headers):
            parts = parts + [""] * (len(headers) - len(parts))
        row = {headers[j]: parts[j] for j in range(len(headers))}
        if row.get(headers[0], "").lower() == headers[0]:
            continue
        rows.append(row)
    return rows


async def _discover_tables(sql: _McpSql, source: SyncSource) -> list[SyncTableSpec]:
    if source.tables:
        return list(source.tables)
    schemas_list = ", ".join(_sql_str(s) for s in source.source_schemas)
    q = (
        f"SELECT table_schema, table_name FROM information_schema.tables "
        f"WHERE table_catalog = {_sql_str(source.alias)} "
        f"AND table_schema IN ({schemas_list}) "
        f"AND table_type = 'BASE TABLE' "
        f"ORDER BY table_schema, table_name"
    )
    # Prefer querying through the attached alias when information_schema is local-only.
    # Fall back to alias.information_schema if needed.
    text = ""
    try:
        text = await sql.execute(
            f"SELECT table_schema, table_name FROM {source.alias}.information_schema.tables "
            f"WHERE table_schema IN ({schemas_list}) "
            f"AND table_type = 'BASE TABLE' "
            f"ORDER BY table_schema, table_name"
        )
    except Exception:
        text = await sql.execute(q)
    rows = _parse_pipe_table(text)
    found: list[SyncTableSpec] = []
    for r in rows:
        ss = (r.get("table_schema") or "").strip()
        st = (r.get("table_name") or "").strip()
        if not ss or not st:
            continue
        try:
            found.append(
                SyncTableSpec(
                    source_schema=_require_ident(ss, label="source_schema"),
                    source_table=_require_ident(st, label="source_table"),
                )
            )
        except ValueError:
            continue
    return found


async def _attach_source(sql: _McpSql, source: SyncSource) -> None:
    await sql.execute("INSTALL quack")
    await sql.execute("LOAD quack")
    secret_name = _require_ident(f"quack_{source.name}", label="secret_name")
    await sql.execute(
        f"CREATE OR REPLACE SECRET {secret_name} ("
        f"TYPE quack, "
        f"TOKEN {_sql_str(source.quack_token)}, "
        f"SCOPE {_sql_str(source.quack_uri)}"
        f")"
    )
    disable = "true" if source.disable_ssl else "false"
    await sql.execute(
        f"ATTACH {_sql_str(source.quack_uri)} AS {source.alias} ("
        f"TYPE quack, "
        f"TOKEN {_sql_str(source.quack_token)}, "
        f"DISABLE_SSL {disable}, "
        f"READ_ONLY"
        f")"
    )


async def _detach_source(sql: _McpSql, source: SyncSource) -> None:
    try:
        await sql.execute(f"DETACH {source.alias}")
    except Exception as exc:
        logger.warning("DETACH %s failed: %s", source.alias, exc)


async def _record_sync(
    sql: _McpSql,
    *,
    source: SyncSource,
    source_fqn: str,
    target_fqn: str,
    row_count: int | None,
    status: str,
    error_message: str | None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    # id = epoch micros for uniqueness without sequences
    rid = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    err = "NULL" if not error_message else _sql_str(error_message[:2000])
    rc = "NULL" if row_count is None else str(int(row_count))
    await sql.execute(
        "INSERT INTO medallion.sync_registry "
        "(id, source_name, source_uri, source_fqn, target_fqn, row_count, status, error_message, synced_at) "
        f"VALUES ({rid}, {_sql_str(source.name)}, {_sql_str(source.quack_uri)}, "
        f"{_sql_str(source_fqn)}, {_sql_str(target_fqn)}, {rc}, {_sql_str(status)}, {err}, "
        f"TIMESTAMP {_sql_str(now)})"
    )


async def _count_rows(sql: _McpSql, fqn: str) -> int | None:
    try:
        text = await sql.execute(f"SELECT COUNT(*) AS n FROM {fqn}")
        rows = _parse_pipe_table(text)
        if rows:
            for key in ("n", "count_star()", "count(*)"):
                if key in rows[0]:
                    return int(float(rows[0][key]))
            # first value
            first = next(iter(rows[0].values()), None)
            if first is not None:
                return int(float(first))
    except Exception as exc:
        logger.warning("COUNT(*) on %s failed: %s", fqn, exc)
    return None


async def run_quack_sync(
    *,
    source_name: str | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Run sync for all enabled sources (or one named source)."""
    sources = load_sync_sources(manifest_path)
    if source_name:
        sources = [s for s in sources if s.name == source_name]
        if not sources:
            return {
                "status": "error",
                "error": f"source {source_name!r} not found or missing credentials",
                "results": [],
            }

    if not sources:
        return {
            "status": "ok",
            "message": "no sync sources configured (see config/sync_sources.yaml + .env)",
            "results": [],
        }

    sql = _McpSql()
    await sql.connect()
    await bootstrap_sync_registry(sql)

    results: list[dict[str, Any]] = []
    for source in sources:
        await sql.execute(f"CREATE SCHEMA IF NOT EXISTS {source.target_schema}")
        try:
            await _attach_source(sql, source)
        except Exception as exc:
            results.append(
                {
                    "source": source.name,
                    "status": "error",
                    "error": f"ATTACH failed: {exc}",
                }
            )
            continue

        try:
            tables = await _discover_tables(sql, source)
            if not tables:
                results.append(
                    {
                        "source": source.name,
                        "status": "ok",
                        "message": "no tables to sync",
                        "tables": [],
                    }
                )
                continue

            table_results: list[dict[str, Any]] = []
            for spec in tables:
                target_table = _require_ident(spec.target_name(), label="target_table")
                target_fqn = f"{source.target_schema}.{target_table}"
                source_ref = f"{source.alias}.{spec.source_schema}.{spec.source_table}"
                try:
                    await sql.execute(
                        f"CREATE OR REPLACE TABLE {target_fqn} AS SELECT * FROM {source_ref}"
                    )
                    n = await _count_rows(sql, target_fqn)
                    await _record_sync(
                        sql,
                        source=source,
                        source_fqn=spec.source_fqn,
                        target_fqn=target_fqn,
                        row_count=n,
                        status="ok",
                        error_message=None,
                    )
                    table_results.append(
                        {
                            "source_fqn": spec.source_fqn,
                            "target_fqn": target_fqn,
                            "row_count": n,
                            "status": "ok",
                        }
                    )
                except Exception as exc:
                    err = str(exc)[:500]
                    try:
                        await _record_sync(
                            sql,
                            source=source,
                            source_fqn=spec.source_fqn,
                            target_fqn=target_fqn,
                            row_count=None,
                            status="error",
                            error_message=err,
                        )
                    except Exception:
                        pass
                    table_results.append(
                        {
                            "source_fqn": spec.source_fqn,
                            "target_fqn": target_fqn,
                            "status": "error",
                            "error": err,
                        }
                    )
            ok = all(t.get("status") == "ok" for t in table_results)
            results.append(
                {
                    "source": source.name,
                    "status": "ok" if ok else "partial",
                    "tables": table_results,
                }
            )
        finally:
            await _detach_source(sql, source)

    overall = "ok"
    if any(r.get("status") == "error" for r in results):
        overall = "error"
    elif any(r.get("status") == "partial" for r in results):
        overall = "partial"
    return {"status": overall, "results": results}


async def sync_status(*, limit: int = 200) -> dict[str, Any]:
    """Latest sync_registry rows (newest first), plus distinct sources."""
    sql = _McpSql()
    try:
        await sql.connect()
        await bootstrap_sync_registry(sql)
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:500], "entries": [], "sources": []}

    lim = max(1, min(int(limit), 1000))
    text = await sql.execute(
        "SELECT id, source_name, source_uri, source_fqn, target_fqn, row_count, "
        "status, error_message, CAST(synced_at AS VARCHAR) AS synced_at "
        f"FROM medallion.sync_registry ORDER BY synced_at DESC, id DESC LIMIT {lim}"
    )
    rows = _parse_pipe_table(text)
    entries: list[dict[str, Any]] = []
    for r in rows:
        rc_raw = (r.get("row_count") or "").strip()
        row_count: int | None
        try:
            row_count = int(float(rc_raw)) if rc_raw and rc_raw.upper() != "NULL" else None
        except ValueError:
            row_count = None
        entries.append(
            {
                "id": (r.get("id") or "").strip(),
                "source_name": (r.get("source_name") or "").strip(),
                "source_uri": (r.get("source_uri") or "").strip(),
                "source_fqn": (r.get("source_fqn") or "").strip(),
                "target_fqn": (r.get("target_fqn") or "").strip(),
                "row_count": row_count,
                "status": (r.get("status") or "").strip(),
                "error_message": (r.get("error_message") or "").strip() or None,
                "synced_at": (r.get("synced_at") or "").strip() or None,
            }
        )

    # Distinct sources from latest successful rows
    sources_map: dict[str, dict[str, Any]] = {}
    for e in entries:
        name = e["source_name"]
        if not name or name in sources_map:
            continue
        sources_map[name] = {
            "name": name,
            "uri": e["source_uri"],
            "last_synced_at": e["synced_at"],
            "last_status": e["status"],
        }

    # Configured sources (may have no registry rows yet)
    configured = []
    for s in load_sync_sources():
        configured.append(
            {
                "name": s.name,
                "alias": s.alias,
                "uri": s.quack_uri,
                "target_schema": s.target_schema,
                "table_count": len(s.tables) if s.tables else None,
            }
        )

    return {
        "status": "ok",
        "entries": entries,
        "sources": list(sources_map.values()),
        "configured_sources": configured,
        "count": len(entries),
    }


def _lineage_html(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    """Inline HTML + vis-network for MCP-UI iframe."""
    payload = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)
    # Escape </script> in JSON
    payload = payload.replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Datasyn Quack Sync Lineage</title>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    html, body {{ margin: 0; height: 100%; font-family: ui-sans-serif, system-ui, sans-serif; background: #0f1419; color: #e7ecf3; }}
    #graph {{ width: 100%; height: 100%; }}
    .empty {{ padding: 1.5rem; color: #9aa7b8; }}
  </style>
</head>
<body>
  <div id="graph"></div>
  <script>
    const DATA = {payload};
    const el = document.getElementById('graph');
    if (!DATA.nodes.length) {{
      el.innerHTML = '<p class="empty">No sync lineage yet. Run a Quack sync to populate medallion.sync_registry.</p>';
    }} else {{
      const nodes = new vis.DataSet(DATA.nodes.map(n => ({{
        id: n.id,
        label: n.label,
        group: n.group,
        title: n.title || n.label
      }})));
      const edges = new vis.DataSet(DATA.edges.map(e => ({{
        id: e.id,
        from: e.from,
        to: e.to,
        arrows: 'to',
        label: e.label || '',
        font: {{ size: 10, color: '#9aa7b8' }}
      }})));
      new vis.Network(el, {{ nodes, edges }}, {{
        physics: {{ stabilization: true, barnesHut: {{ gravitationalConstant: -12000 }} }},
        groups: {{
          external: {{ color: {{ background: '#3d4f66', border: '#7eb8ff' }}, shape: 'box' }},
          main: {{ color: {{ background: '#1e3a2f', border: '#5dcea3' }}, shape: 'box' }},
          source: {{ color: {{ background: '#3a2f1e', border: '#e6b35c' }}, shape: 'ellipse' }}
        }},
        interaction: {{ hover: true, tooltipDelay: 120 }}
      }});
    }}
  </script>
</body>
</html>
"""


async def build_lineage_ui_resource() -> dict[str, Any]:
    """MCP Apps / MCP-UI UIResource for sync lineage (ui://datasyn/lineage)."""
    status = await sync_status(limit=500)
    entries = status.get("entries") or []

    # Deduplicate edges by latest ok/error per (source_name, source_fqn, target_fqn)
    seen: set[str] = set()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for e in entries:
        source_name = e.get("source_name") or "external"
        source_fqn = e.get("source_fqn") or ""
        target_fqn = e.get("target_fqn") or ""
        if not source_fqn or not target_fqn:
            continue
        key = f"{source_name}|{source_fqn}|{target_fqn}"
        if key in seen:
            continue
        seen.add(key)

        src_id = f"ext:{source_name}:{source_fqn}"
        tgt_id = f"main:{target_fqn}"
        inst_id = f"src:{source_name}"

        if inst_id not in nodes:
            nodes[inst_id] = {
                "id": inst_id,
                "label": source_name,
                "group": "source",
                "title": e.get("source_uri") or source_name,
            }
        if src_id not in nodes:
            nodes[src_id] = {
                "id": src_id,
                "label": source_fqn,
                "group": "external",
                "title": f"{source_name} · {source_fqn}",
            }
        if tgt_id not in nodes:
            nodes[tgt_id] = {
                "id": tgt_id,
                "label": target_fqn,
                "group": "main",
                "title": f"main · {target_fqn}",
            }

        edges.append(
            {
                "id": f"e-{len(edges)}-inst-src",
                "from": inst_id,
                "to": src_id,
                "label": "",
            }
        )
        edges.append(
            {
                "id": f"e-{len(edges)}-sync",
                "from": src_id,
                "to": tgt_id,
                "label": e.get("status") or "sync",
            }
        )

    html = _lineage_html(list(nodes.values()), edges)
    resource = {
        "uri": "ui://datasyn/lineage",
        "mimeType": "text/html",
        "text": html,
    }
    return {
        "status": status.get("status", "ok"),
        "type": "resource",
        "resource": resource,
        # MCP Apps tool metadata shape (for hosts that expect _meta.ui)
        "_meta": {"ui": {"resourceUri": "ui://datasyn/lineage"}},
        "entry_count": len(entries),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "error": status.get("error"),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: ``uv run quack-sync [--source NAME]``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Sync external Quack DuckDB tables into the main warehouse")
    parser.add_argument("--source", help="Only sync this source name from sync_sources.yaml")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to sync_sources.yaml (default: <project>/config/sync_sources.yaml)",
    )
    parser.add_argument("--status", action="store_true", help="Print sync_registry status and exit")
    args = parser.parse_args(argv)

    if args.status:
        payload = asyncio.run(sync_status())
    else:
        payload = asyncio.run(run_quack_sync(source_name=args.source, manifest_path=args.manifest))
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") in ("ok", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
