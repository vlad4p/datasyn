"""Export agent chat sessions as report-style analyses under reports/analyses/."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.config import settings

_ANALYSES_SUBDIR = "analyses"
_PREVIEW_MAX = 280
_TITLE_MAX = 120


def _analyses_root() -> Path:
    root = settings.reports_dir.resolve() / _ANALYSES_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _preview_text(text: str) -> str:
    flat = re.sub(r"\s+", " ", (text or "").strip())
    if len(flat) <= _PREVIEW_MAX:
        return flat
    return flat[: _PREVIEW_MAX - 1].rstrip() + "…"


def _default_title(messages: list[dict[str, str]], locale: str) -> str:
    for m in messages:
        if m.get("role") == "user" and (m.get("content") or "").strip():
            t = (m["content"] or "").strip().split("\n")[0]
            return t[:_TITLE_MAX]
    return "Análisis" if locale == "es" else "Analysis"


def _build_report_md(
    *,
    analysis_id: str,
    title: str,
    locale: str,
    messages: list[dict[str, str]],
    dataset_fqn: str | None,
    request_ids: list[str],
    exported_at: str,
) -> str:
    is_es = locale == "es"
    lines: list[str] = [
        f"# {title}",
        "",
        f"**{'Exportado' if is_es else 'Exported'}:** {exported_at}",
        f"**ID:** `{analysis_id}`",
    ]
    if dataset_fqn:
        lines.append(f"**{'Dataset' if is_es else 'Dataset'}:** `{dataset_fqn}`")
    lines.extend(["", "---", ""])

    lines.append(f"## {'Resumen ejecutivo' if is_es else 'Executive summary'}")
    lines.append("")
    first_assistant = next(
        (m.get("content", "") for m in messages if m.get("role") == "assistant" and m.get("content")),
        "",
    )
    if first_assistant.strip():
        excerpt = first_assistant.strip()
        if len(excerpt) > 1200:
            excerpt = excerpt[:1200].rstrip() + "\n\n…"
        lines.append(excerpt)
    else:
        lines.append("_" + ("Sin respuesta del agente." if is_es else "No agent reply.") + "_")
    lines.extend(["", "---", ""])

    if request_ids:
        lines.append(f"## {'Método' if is_es else 'Method'}")
        lines.append("")
        lines.append(f"{'IDs de solicitud' if is_es else 'Request IDs'}:")
        for rid in request_ids:
            lines.append(f"- `{rid}`")
        lines.extend(["", "---", ""])

    lines.append(f"## {'Hallazgos' if is_es else 'Findings'}")
    lines.append("")
    for i, m in enumerate(messages, 1):
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        label = "Usuario" if role == "user" else "Agente"
        if is_es:
            label = "Usuario" if role == "user" else "Agente"
        else:
            label = "User" if role == "user" else "Agent"
        lines.append(f"### {label} ({i})")
        lines.append("")
        lines.append(content)
        lines.append("")
    lines.extend(["---", ""])
    lines.append(f"## {'Limitaciones' if is_es else 'Limitations'}")
    lines.append("")
    lines.append(
        "_"
        + (
            "Exportación generada desde el chat del agente; validar cifras con SQL reproducible."
            if is_es
            else "Export generated from agent chat; validate figures with reproducible SQL."
        )
        + "_"
    )
    lines.append("")
    return "\n".join(lines)


def export_analysis(
    *,
    messages: list[dict[str, str]],
    locale: str = "en",
    title: str | None = None,
    dataset_fqn: str | None = None,
    request_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Write report.md + manifest.json; return manifest dict."""
    analysis_id = str(uuid4())
    exported_at = datetime.now(timezone.utc).isoformat()
    resolved_title = (title or "").strip() or _default_title(messages, locale)
    req_ids = [r for r in (request_ids or []) if r]

    all_text = "\n".join(m.get("content", "") for m in messages)
    preview = _preview_text(all_text)

    dir_path = _analyses_root() / analysis_id
    dir_path.mkdir(parents=True, exist_ok=True)
    report_rel = f"reports/{_ANALYSES_SUBDIR}/{analysis_id}/report.md"
    report_path = dir_path / "report.md"
    report_path.write_text(
        _build_report_md(
            analysis_id=analysis_id,
            title=resolved_title,
            locale=locale,
            messages=messages,
            dataset_fqn=dataset_fqn,
            request_ids=req_ids,
            exported_at=exported_at,
        ),
        encoding="utf-8",
    )

    manifest = {
        "id": analysis_id,
        "title": resolved_title,
        "created_at": exported_at,
        "dataset_fqn": dataset_fqn,
        "preview": preview,
        "message_count": len([m for m in messages if (m.get("content") or "").strip()]),
        "report_path": report_rel,
        "locale": locale,
    }
    (dir_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def list_analyses(limit: int = 50) -> list[dict[str, Any]]:
    root = _analyses_root()
    items: list[dict[str, Any]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        mf = child / "manifest.json"
        if not mf.is_file():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                items.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items[:limit]


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    aid = analysis_id.strip()
    if not aid or ".." in Path(aid).parts:
        return None
    dir_path = _analyses_root() / aid
    mf = dir_path / "manifest.json"
    rf = dir_path / "report.md"
    if not mf.is_file():
        return None
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    report_md = ""
    if rf.is_file():
        try:
            report_md = rf.read_text(encoding="utf-8")
        except OSError:
            report_md = ""
    return {"manifest": manifest, "report_md": report_md}
