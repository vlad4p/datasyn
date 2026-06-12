"""Push local skills to LiteLLM registry + pull bundle for runtime."""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent.skills.bundle import create_skills_bundle, extract_skills_bundle
from agent.skills.config import SkillsSettings, skills_settings
from agent.skills.discovery import discover_skills
from agent.skills.litellm_client import LiteLLMSkillsClient

logger = logging.getLogger(__name__)


def _publish_bundle_file(*, cfg: SkillsSettings, bundle_path: Path) -> Path:
    """Copy tarball into the LiteLLM skills-bundles directory (bind-mounted in compose)."""
    if cfg.bundle_publish_dir is None:
        raise ValueError(
            "LITELLM_SKILLS_BUNDLE_DIR is not set and infra/litellm/skills-bundles/ was not found. "
            "Set LITELLM_SKILLS_BUNDLE_DIR to the directory LiteLLM serves, or set "
            "LITELLM_SKILLS_BUNDLE_URL to an existing bundle URL."
        )
    dest = cfg.bundle_publish_dir / cfg.bundle_filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle_path, dest)
    return dest


def _publish_skill_trees(*, cfg: SkillsSettings, skills_root: Path, skill_names: list[str]) -> Path:
    """Copy every skill directory tree for static HTTP serving (``/skills/<name>/...``)."""
    if cfg.bundle_publish_dir is None:
        raise ValueError("LITELLM_SKILLS_BUNDLE_DIR is required to publish skill trees")
    dest_root = cfg.bundle_publish_dir / "skills"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    for name in skill_names:
        src = skills_root / name
        shutil.copytree(src, dest_root / name)
    return dest_root


def _bundle_url_for_push(cfg: SkillsSettings) -> str:
    if cfg.bundle_url:
        return cfg.bundle_url
    if cfg.bundle_public_url:
        return cfg.bundle_public_url
    raise ValueError(
        "Set LITELLM_SKILLS_BUNDLE_URL or LITELLM_SKILLS_STATIC_BASE (or LITELLM_PROXY_BASE) "
        "so LiteLLM can resolve the bundle download URL after push."
    )


def download_bundle(*, url: str, dest_path: Path) -> Path:
    """Download skills bundle over HTTP(S)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest_path.write_bytes(resp.content)
    return dest_path


def push_skills_to_litellm(*, cfg: SkillsSettings | None = None, skills_root: Path | None = None) -> dict:
    """Publish every ``./skills/*/`` tree to LiteLLM (one plugin per skill + aggregate bundle)."""
    cfg = cfg or skills_settings
    root = (skills_root or cfg.local_dir).resolve()
    names = discover_skills(root)
    if not names:
        raise ValueError(f"No skills with SKILL.md under {root}")

    with tempfile.TemporaryDirectory(prefix="datasyn-skills-push-") as tmp:
        bundle_path = Path(tmp) / cfg.bundle_filename
        create_skills_bundle(skills_root=root, output_path=bundle_path)
        published_path = _publish_bundle_file(cfg=cfg, bundle_path=bundle_path)
        skills_dir = _publish_skill_trees(cfg=cfg, skills_root=root, skill_names=names)

    bundle_url = _bundle_url_for_push(cfg)
    version = datetime.now(UTC).strftime("%Y.%m.%d.%H%M")
    client = LiteLLMSkillsClient(cfg)
    skill_plugins, removed_plugins = client.sync_skill_plugins(skill_names=names, version=version)
    bundle_plugin = client.register_bundle_plugin(bundle_url=bundle_url, version=version, skill_count=len(names))
    client.enable_plugin(cfg.plugin_name)

    logger.info(
        "skills push: uploaded %s skills (%s) — bundle %s, plugins %s",
        len(names),
        ", ".join(names),
        bundle_url,
        ", ".join(p["plugin"] for p in skill_plugins),
    )
    if removed_plugins:
        logger.info("skills push: removed stale plugins: %s", ", ".join(removed_plugins))

    return {
        "ok": True,
        "skills": names,
        "skill_count": len(names),
        "skill_plugins": skill_plugins,
        "removed_plugins": removed_plugins,
        "bundle_url": bundle_url,
        "published_path": str(published_path),
        "skills_static_dir": str(skills_dir),
        "plugin": bundle_plugin,
        "version": version,
    }


def pull_skills_from_litellm(*, cfg: SkillsSettings | None = None, target_dir: Path | None = None) -> dict:
    """Download skills bundle from LiteLLM registry and extract to cache directory."""
    cfg = cfg or skills_settings
    target = (target_dir or cfg.cache_dir).resolve()
    client = LiteLLMSkillsClient(cfg)
    bundle_url = client.resolve_bundle_url()

    with tempfile.TemporaryDirectory(prefix="datasyn-skills-pull-") as tmp:
        bundle_path = Path(tmp) / cfg.bundle_filename
        download_bundle(url=bundle_url, dest_path=bundle_path)
        extract_skills_bundle(bundle_path=bundle_path, target_dir=target)

    names = discover_skills(target)
    if not names:
        raise ValueError(f"Pulled bundle into {target} but no skills were discovered")
    logger.info("skills pull: extracted %s skills into %s from %s", len(names), target, bundle_url)
    return {
        "ok": True,
        "skills": names,
        "cache_dir": str(target),
        "bundle_url": bundle_url,
    }
