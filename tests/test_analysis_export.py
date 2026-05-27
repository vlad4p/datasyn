"""Analysis export helpers (run: uv run pytest tests/test_analysis_export.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.utils.analysis_export import export_analysis, get_analysis, list_analyses


@pytest.fixture()
def reports_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    root.mkdir()

    def _root() -> Path:
        analyses = root / "analyses"
        analyses.mkdir(parents=True, exist_ok=True)
        return analyses

    monkeypatch.setattr("agent.utils.analysis_export._analyses_root", _root)
    return root


def test_export_and_list(reports_tmp: Path) -> None:
    manifest = export_analysis(
        messages=[
            {"role": "user", "content": "Count rows in gold.sales"},
            {"role": "assistant", "content": "There are **42** rows."},
        ],
        locale="en",
        title="Sales check",
    )
    assert manifest["title"] == "Sales check"
    assert manifest["message_count"] == 2
    aid = manifest["id"]
    report_path = reports_tmp / "analyses" / aid / "report.md"
    assert report_path.is_file()
    mf = reports_tmp / "analyses" / aid / "manifest.json"
    assert json.loads(mf.read_text(encoding="utf-8"))["id"] == aid

    listed = list_analyses()
    assert any(x["id"] == aid for x in listed)

    detail = get_analysis(aid)
    assert detail is not None
    assert "42" in detail["report_md"]
    assert detail["manifest"]["title"] == "Sales check"
