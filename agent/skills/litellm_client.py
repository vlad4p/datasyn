"""LiteLLM Skills Gateway (``/claude-code/plugins``) client."""

from __future__ import annotations

from typing import Any

import httpx

from agent.skills.config import SkillsSettings


class LiteLLMSkillsClient:
    """Register and resolve Datasyn skills via LiteLLM's plugin registry."""

    def __init__(self, cfg: SkillsSettings) -> None:
        if not cfg.litellm_key:
            raise ValueError(
                "LITELLM_KEY (or LITELLM_MASTER_KEY) is required for LiteLLM skills sync. "
                "Set it in the repo root `.env`."
            )
        self._cfg = cfg
        self._root = cfg.litellm_proxy_root.rstrip("/")
        self._headers = {"Authorization": f"Bearer {cfg.litellm_key}"}

    def list_plugins(self) -> list[dict[str, Any]]:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{self._root}/claude-code/plugins", headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
        plugins = data.get("plugins")
        if isinstance(plugins, list):
            return plugins
        return []

    def get_plugin(self, name: str) -> dict[str, Any] | None:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{self._root}/claude-code/plugins/{name}", headers=self._headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    def delete_plugin(self, name: str) -> None:
        with httpx.Client(timeout=30.0) as client:
            resp = client.delete(f"{self._root}/claude-code/plugins/{name}", headers=self._headers)
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()

    def _upsert_plugin(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "")
        existing = self.get_plugin(name) if name else None
        with httpx.Client(timeout=60.0) as client:
            if existing:
                resp = client.delete(f"{self._root}/claude-code/plugins/{name}", headers=self._headers)
                if resp.status_code not in (200, 204, 404):
                    resp.raise_for_status()
            resp = client.post(
                f"{self._root}/claude-code/plugins",
                headers={**self._headers, "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def enable_plugin(self, name: str | None = None) -> None:
        plugin_name = name or self._cfg.plugin_name
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{self._root}/claude-code/plugins/{plugin_name}/enable",
                headers=self._headers,
            )
            resp.raise_for_status()

    def register_bundle_plugin(self, *, bundle_url: str, version: str, skill_count: int) -> dict[str, Any]:
        """Create or update the aggregate bundle plugin used by brain pull."""
        return self._upsert_plugin(
            {
                "name": self._cfg.plugin_name,
                "source": {"source": "url", "url": bundle_url},
                "description": f"Datasyn warehouse agent skills bundle ({skill_count} skills)",
                "domain": "Datasyn",
                "namespace": "warehouse",
                "keywords": ["datasyn", "skills", "warehouse", "bundle"],
                "version": version,
            }
        )

    def register_skill_plugin(self, *, skill_name: str, skill_url: str, version: str) -> dict[str, Any]:
        """Create or update one skill plugin in LiteLLM Skills Gateway."""
        plugin_name = self._cfg.litellm_plugin_name_for_skill(skill_name)
        return self._upsert_plugin(
            {
                "name": plugin_name,
                "source": {"source": "url", "url": skill_url},
                "description": f"Datasyn skill: {skill_name}",
                "domain": "Datasyn",
                "namespace": "warehouse",
                "keywords": ["datasyn", "skill", skill_name],
                "version": version,
            }
        )

    def sync_skill_plugins(
        self,
        *,
        skill_names: list[str],
        version: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Register every local skill and remove stale ``{prefix}-*`` plugins."""
        registered: list[dict[str, Any]] = []
        prefix = self._cfg.skill_plugin_prefix
        expected = {self._cfg.litellm_plugin_name_for_skill(n) for n in skill_names}

        for skill_name in skill_names:
            skill_url = self._cfg.skill_static_url(skill_name)
            plugin = self.register_skill_plugin(skill_name=skill_name, skill_url=skill_url, version=version)
            self.enable_plugin(self._cfg.litellm_plugin_name_for_skill(skill_name))
            registered.append(
                {
                    "skill": skill_name,
                    "plugin": self._cfg.litellm_plugin_name_for_skill(skill_name),
                    "url": skill_url,
                    "litellm": plugin,
                }
            )

        removed: list[str] = []
        if prefix:
            for plugin in self.list_plugins():
                name = str(plugin.get("name") or "")
                if not name.startswith(f"{prefix}-"):
                    continue
                if name == self._cfg.plugin_name:
                    continue
                if name in expected:
                    continue
                self.delete_plugin(name)
                removed.append(name)

        return registered, removed

    def resolve_bundle_url(self) -> str:
        """Return bundle URL from env override or registered plugin metadata."""
        if self._cfg.bundle_url:
            return self._cfg.bundle_url
        plugin = self.get_plugin(self._cfg.plugin_name)
        if not plugin:
            raise ValueError(
                f"LiteLLM plugin {self._cfg.plugin_name!r} not found. "
                "Run `uv run skills-sync push` or set LITELLM_SKILLS_BUNDLE_URL."
            )
        source = plugin.get("source") or {}
        if isinstance(source, dict):
            url = source.get("url")
            if isinstance(url, str) and url.strip():
                return url.strip()
        raise ValueError(
            f"LiteLLM plugin {self._cfg.plugin_name!r} has no bundle URL in source. "
            "Run `uv run skills-sync push` or set LITELLM_SKILLS_BUNDLE_URL."
        )
