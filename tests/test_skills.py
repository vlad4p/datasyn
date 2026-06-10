"""Tests for skills discovery, bundles, and resolver."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from agent.skills.bundle import create_skills_bundle, extract_skills_bundle
from agent.skills.config import SkillsSettings
from agent.skills.discovery import discover_skills
from agent.skills.resolver import resolve_skills_root


def test_discover_skills(tmp_path: Path) -> None:
    (tmp_path / "alpha" / "SKILL.md").parent.mkdir(parents=True)
    (tmp_path / "alpha" / "SKILL.md").write_text("# Alpha\n", encoding="utf-8")
    (tmp_path / "beta" / "SKILL.md").parent.mkdir(parents=True)
    (tmp_path / "beta" / "SKILL.md").write_text("# Beta\n", encoding="utf-8")
    (tmp_path / "empty-dir").mkdir()

    assert discover_skills(tmp_path) == ["alpha", "beta"]


def test_bundle_roundtrip(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    (skills_root / "demo" / "SKILL.md").parent.mkdir(parents=True)
    (skills_root / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    (skills_root / "demo" / "extra.txt").write_text("helper\n", encoding="utf-8")

    bundle = tmp_path / "bundle.tar.gz"
    create_skills_bundle(skills_root=skills_root, output_path=bundle)
    assert bundle.is_file()

    target = tmp_path / "out"
    extract_skills_bundle(bundle_path=bundle, target_dir=target)
    assert (target / "demo" / "SKILL.md").read_text(encoding="utf-8").startswith("---")
    assert (target / "demo" / "extra.txt").read_text(encoding="utf-8") == "helper\n"


def test_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    bundle = tmp_path / "evil.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"evil"))

    with pytest.raises(tarfile.TarError):
        extract_skills_bundle(bundle_path=bundle, target_dir=tmp_path / "out")


def test_create_skills_bundle_includes_all_discovered_skills(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    for name in ("alpha", "beta"):
        (skills_root / name / "SKILL.md").parent.mkdir(parents=True)
        (skills_root / name / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skills_root / name / "extra.txt").write_text("x\n", encoding="utf-8")

    bundle = tmp_path / "all.tar.gz"
    create_skills_bundle(skills_root=skills_root, output_path=bundle)

    import tarfile

    with tarfile.open(bundle, "r:gz") as tar:
        members = {m.name for m in tar.getmembers()}
    assert "alpha/SKILL.md" in members
    assert "alpha/extra.txt" in members
    assert "beta/SKILL.md" in members


def test_resolve_skills_root_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local = tmp_path / "skills"
    local.mkdir()
    cfg = SkillsSettings(
        source="local",
        local_dir=local,
        cache_dir=tmp_path / "cache",
        plugin_name="datasyn-skills",
        skill_plugin_prefix="datasyn",
        bundle_url=None,
        bundle_filename="datasyn-bundle.tar.gz",
        bundle_public_url="http://127.0.0.1:4001/datasyn-bundle.tar.gz",
        bundle_publish_dir=tmp_path / "publish",
        litellm_key=None,
        litellm_proxy_root="http://127.0.0.1:4000",
    )
    monkeypatch.setattr("agent.skills.resolver.skills_settings", cfg)
    assert resolve_skills_root(cfg=cfg) == local
