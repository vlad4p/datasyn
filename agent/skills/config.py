"""Skills source configuration (local ``./skills`` vs LiteLLM-pulled cache)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent.config import _env_first, _litellm_base_from_env, settings

SkillsSource = Literal["local", "litellm"]

_DEFAULT_LITELLM_PROXY = "http://127.0.0.1:4000"


def _skills_source() -> SkillsSource:
    raw = (os.environ.get("SKILLS_SOURCE") or "local").strip().lower()
    if raw in ("local", "filesystem", "fs"):
        return "local"
    if raw in ("litellm", "remote", "registry"):
        return "litellm"
    raise ValueError(f"SKILLS_SOURCE must be 'local' or 'litellm', got {raw!r}")


def _read_infra_litellm_dotenv(project_root: Path) -> dict[str, str]:
    """Parse ``infra/litellm/.env`` without mutating ``os.environ``."""
    path = project_root / "infra" / "litellm" / ".env"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and value:
            out[key] = value
    return out


def _litellm_proxy_root(*, project_root: Path) -> str:
    """LiteLLM admin routes (``/claude-code/plugins``) live on the proxy root, not ``/v1``."""
    base = _litellm_base_from_env()
    if base:
        return base.removesuffix("/v1").rstrip("/")
    explicit = (os.environ.get("LITELLM_PROXY_ROOT") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    return _DEFAULT_LITELLM_PROXY


def _litellm_key_for_skills(*, project_root: Path) -> str | None:
    key = _env_first("LITELLM_KEY", "LITELLM_PROXY_KEY", "LITELLM_MASTER_KEY")
    if key:
        return key
    infra = _read_infra_litellm_dotenv(project_root)
    return infra.get("LITELLM_MASTER_KEY") or infra.get("LITELLM_KEY") or infra.get("LITELLM_PROXY_KEY")


def _default_bundle_filename() -> str:
    return (os.environ.get("LITELLM_SKILLS_BUNDLE_NAME") or "datasyn-bundle.tar.gz").strip()


def _default_bundle_public_url(*, filename: str) -> str | None:
    """HTTP URL for the skills bundle served by ``skills-static`` (see infra/litellm)."""
    explicit = _env_first("LITELLM_SKILLS_BUNDLE_URL", "SKILLS_BUNDLE_URL")
    if explicit:
        return explicit
    static_base = _env_first("LITELLM_SKILLS_STATIC_BASE") or "http://127.0.0.1:4001"
    return f"{static_base.rstrip('/')}/{filename}"


def skills_static_base() -> str:
    return (_env_first("LITELLM_SKILLS_STATIC_BASE") or "http://127.0.0.1:4001").rstrip("/")


def skill_plugin_name(*, prefix: str, skill_name: str) -> str:
    """LiteLLM plugin names must match ``^[a-z0-9-]+$``."""
    slug = skill_name.strip().lower().replace("_", "-")
    p = prefix.strip()
    return f"{p}-{slug}" if p else slug


@dataclass(frozen=True)
class SkillsSettings:
    source: SkillsSource
    local_dir: Path
    cache_dir: Path
    plugin_name: str
    skill_plugin_prefix: str
    bundle_url: str | None
    bundle_filename: str
    bundle_public_url: str | None
    bundle_publish_dir: Path | None
    litellm_key: str | None
    litellm_proxy_root: str

    def skill_static_url(self, skill_name: str) -> str:
        """Public URL for one skill's ``SKILL.md`` (served under ``skills-static``)."""
        return f"{skills_static_base()}/skills/{skill_name}/SKILL.md"

    def litellm_plugin_name_for_skill(self, skill_name: str) -> str:
        return skill_plugin_name(prefix=self.skill_plugin_prefix, skill_name=skill_name)

    @classmethod
    def load(cls, *, project_root: Path | None = None) -> SkillsSettings:
        root = (project_root or settings.project_root).resolve()
        local = Path(os.environ.get("SKILLS_LOCAL_DIR", str(root / "skills"))).expanduser()
        cache = Path(os.environ.get("SKILLS_CACHE_DIR", str(root / ".cache" / "skills"))).expanduser()
        filename = _default_bundle_filename()
        publish_raw = os.environ.get("LITELLM_SKILLS_BUNDLE_DIR", "").strip()
        publish_dir = Path(publish_raw).expanduser().resolve() if publish_raw else None
        if publish_dir is None:
            default_publish = root / "infra" / "litellm" / "skills-bundles"
            if default_publish.parent.is_dir():
                publish_dir = default_publish.resolve()
        return cls(
            source=_skills_source(),
            local_dir=local.resolve(),
            cache_dir=cache.resolve(),
            plugin_name=(os.environ.get("LITELLM_SKILLS_PLUGIN") or "datasyn-skills").strip(),
            skill_plugin_prefix=(os.environ.get("LITELLM_SKILLS_PLUGIN_PREFIX") or "datasyn").strip(),
            bundle_url=_env_first("LITELLM_SKILLS_BUNDLE_URL", "SKILLS_BUNDLE_URL"),
            bundle_filename=filename,
            bundle_public_url=_default_bundle_public_url(filename=filename),
            bundle_publish_dir=publish_dir,
            litellm_key=_litellm_key_for_skills(project_root=root),
            litellm_proxy_root=_litellm_proxy_root(project_root=root),
        )


skills_settings = SkillsSettings.load()
